"""Shared Revit-side export: active 3D view (or demo) -> glTF bundle.

Used by Load View (extraction) and by Render View / Open View (which read
the cache), so the extraction path is identical. IronPython 2.7 safe. The caller
passes the active doc (it holds __revit__) and a report(msg) callback for output.
"""
import datetime
import os

import bir_bootstrap
bir_bootstrap.ensure_paths()

from bir_contract.transport import get_exporter, SCENE_SPEC_FILENAME
import bir_transports.gltf.exporter  # noqa: F401  registers the "gltf" exporter

_BLEND_NAME = "scene.blend"


def _render_overrides(cfg):
    return {"mode": cfg.get("mode"), "engine": cfg.get("engine"),
            "samples": cfg.get("samples"), "resolution": cfg.get("resolution"),
            "denoise": cfg.get("denoise")}


def extract_or_demo(doc, cfg, report, progress=None, view=None):
    """-> (spec_dict, meshes). Real view extraction (the active view, or an
    explicit `view` - the Views list's Reload), demo box fallback."""
    overrides = _render_overrides(cfg)
    if doc is None:
        report("- no active Revit document -> using demo box")
    else:
        try:
            from bir_extract import revit_extract
            if view is None:
                view = revit_extract.active_view(doc)
            if view is None:
                report("- active view can't be loaded -> using demo box "
                       "(open a 3D, plan, section or elevation view)")
            else:
                report("- extracting view `%s`..." % view.Name)
                spec, meshes = revit_extract.build_scene_spec(
                    doc, view, render_overrides=overrides, progress=progress)
                if meshes:
                    report("- extracted %d mesh group(s) from `%s`"
                           % (len(meshes), view.Name))
                    return spec, meshes
                report("- no geometry extracted -> using demo box")
        except Exception as ex:
            report("- extraction error (%s) -> using demo box" % ex)
    from bir_extract import demo
    spec, meshes = demo.build_demo_bundle()
    spec.setdefault("render", {}).update(overrides)
    return spec, meshes


def export_bundle(doc, cfg, report, progress=None, out_dir=None, view=None):
    """-> (bundle_ref, out_dir). Extract + write the glTF bundle. `out_dir` lets
    callers (Load View) target the model cache instead of the render folder."""
    spec, meshes = extract_or_demo(doc, cfg, report, progress=progress, view=view)
    report("- writing the glTF bundle...")
    if out_dir is None:
        out_dir = cfg.get("output_dir") or bir_bootstrap.default_output_dir()
    bundle_ref = get_exporter("gltf").export(spec, meshes, out_dir)
    return bundle_ref, out_dir


def export_bundle_with_progress(doc, cfg, report, out_dir=None, view=None):
    """export_bundle wrapped in a pyRevit progress bar when available (the
    extraction over thousands of elements is the main wait). Falls back to a
    plain export if pyRevit forms aren't available."""
    try:
        from pyrevit import forms
    except Exception:
        forms = None
    if forms is None:
        return export_bundle(doc, cfg, report, out_dir=out_dir, view=view)

    title = "Blendit - extracting model... ({value} of {max_value})"
    with forms.ProgressBar(title=title) as pb:
        def progress(done, total):
            try:
                pb.update_progress(done, total)
            except Exception:
                pass
        return export_bundle(doc, cfg, report, progress=progress,
                             out_dir=out_dir, view=view)


# --- model cache (one slot PER VIEW) -------------------------------------------
# Layout: <cache_root>/<doc_key>/views/<view_key>/{scene_spec.json, scene.glb,
# textures/, scene.blend, fingerprint.json}. Every loaded view keeps its own
# bundle, so plans / sections / 3D shots coexist and the Views list can offer
# them all. Pre-multiview caches lived at the <doc_key> root; cached_bundle
# still falls back to that legacy slot so nothing breaks on upgrade.

def _active_view(doc):
    try:
        from bir_extract import revit_extract
        return revit_extract.active_view(doc)
    except Exception:
        return None


def cache_paths(doc, view=None, create=False):
    """-> (cache_dir, bundle_ref, blend_path) for one VIEW of this document
    (`view` None = the active view). Falls back to the legacy per-doc root when
    no view can be resolved (headless / tests / non-loadable active view).

    `create` makes the slot directory; the WRITE path (refresh_cache) passes it. The
    read-only queries (cached_bundle / staleness, called on every ribbon refresh for
    whatever view is active) leave it False so merely inspecting a not-yet-loaded
    view never litters an empty slot dir under the cache root."""
    root = bir_bootstrap.cache_dir_for(bir_bootstrap.doc_cache_key(doc))
    if view is None:
        view = _active_view(doc)
    if view is None:
        cdir = root
    else:
        cdir = os.path.join(root, "views", bir_bootstrap.view_cache_key(view))
        if create and not os.path.isdir(cdir):
            try:
                os.makedirs(cdir)
            except Exception:
                pass
    return (cdir,
            os.path.join(cdir, SCENE_SPEC_FILENAME),
            os.path.join(cdir, _BLEND_NAME))


def cached_bundle(doc, view=None):
    """-> (bundle_ref, blend_path) if a cached extraction exists for this view
    (falling back to the legacy per-doc slot), else (None, blend_path)."""
    cdir, bundle_ref, blend_path = cache_paths(doc, view)
    if os.path.isfile(bundle_ref):
        return bundle_ref, blend_path
    root = bir_bootstrap.cache_dir_for(bir_bootstrap.doc_cache_key(doc))
    legacy = os.path.join(root, SCENE_SPEC_FILENAME)
    if os.path.isfile(legacy):
        return legacy, os.path.join(root, _BLEND_NAME)
    return None, blend_path


def refresh_cache(doc, cfg, report, view=None):
    """(Re-)extract a view (`view` None = the active view) into ITS cache slot
    and invalidate that slot's prepared .blend. -> (bundle_ref, blend_path)."""
    if view is None:
        view = _active_view(doc)
    cdir, bundle_ref, blend_path = cache_paths(doc, view, create=True)
    bundle_ref, _ = export_bundle_with_progress(doc, cfg, report,
                                                out_dir=cdir, view=view)
    try:
        if os.path.isfile(blend_path):
            os.remove(blend_path)  # the .blend no longer matches the geometry
    except Exception:
        pass
    save_fingerprint(doc, cdir, view)   # what the model looked like at Load
    return bundle_ref, blend_path


_BUSY_SUFFIX = ".busy"
_BUSY_STALE_S = 45 * 60      # a crashed build's sentinel expires after 45 min


def cache_state(blend_path):
    """-> 'ready' | 'building' | 'none' for a slot's fast-open scene cache.
    'building' = the background build's sentinel exists and is fresh."""
    if os.path.isfile(blend_path):
        return "ready"
    busy = blend_path + _BUSY_SUFFIX
    try:
        import time
        if os.path.isfile(busy) and \
                (time.time() - os.path.getmtime(busy)) < _BUSY_STALE_S:
            return "building"
    except Exception:
        pass
    return "none"


def loaded_views(doc):
    """-> [slot dicts] for every view loaded from this document, newest first.
    Each: {view_name, view_kind, view_uid, loaded_at, cache_dir, bundle_ref,
    blend_path}."""
    root = bir_bootstrap.cache_dir_for(bir_bootstrap.doc_cache_key(doc))
    vroot = os.path.join(root, "views")
    out = []
    try:
        names = os.listdir(vroot)
    except Exception:
        return out
    for name in sorted(names):
        cdir = os.path.join(vroot, name)
        bundle_ref = os.path.join(cdir, SCENE_SPEC_FILENAME)
        if not os.path.isfile(bundle_ref):
            continue
        meta = _load_fingerprint(cdir) or {}
        out.append({
            "view_name": meta.get("view") or name,
            "view_kind": meta.get("view_kind") or "",
            "view_uid": meta.get("view_uid") or "",
            "loaded_at": meta.get("loaded_at") or "",
            "cache_dir": cdir,
            "bundle_ref": bundle_ref,
            "blend_path": os.path.join(cdir, _BLEND_NAME),
        })
    out.sort(key=lambda d: d.get("loaded_at") or "", reverse=True)
    return out


def resolve_view(doc, uid):
    """The live view element for a slot's stored UniqueId, or None (deleted)."""
    if not uid:
        return None
    try:
        return doc.GetElement(uid)
    except Exception:
        return None


def remove_slot(slot):
    """Delete one loaded view's cache slot. True on success."""
    import shutil
    try:
        shutil.rmtree(slot["cache_dir"])
        return True
    except Exception:
        return False


# --- staleness fingerprint ------------------------------------------------
# Saved at Load View time so Open View / Render View / the Views list can warn
# when a cached extraction no longer matches the model ("why is my new wall
# missing?"). Deliberately cheap and approximate: visible element count + the
# model file's mtime (+ the view identity for the meta). A soft signal, never a
# blocker.
_FINGERPRINT_NAME = "fingerprint.json"


def _view_meta(view):
    """Best-effort identity for a view - duck-typed, no Revit API needed."""
    meta = {}
    try:
        meta["view"] = str(view.Name)
    except Exception:
        pass
    try:
        meta["view_uid"] = str(view.UniqueId)
    except Exception:
        pass
    try:
        from bir_extract import camera
        meta["view_kind"] = camera.view_kind(view)
    except Exception:
        pass
    return meta


def _model_fingerprint(doc, view=None):
    """-> {elements, file_mtime} for the CURRENT model state as seen by `view`
    (None = active view), or None when it can't be computed (headless / no doc)."""
    if doc is None:
        return None
    try:
        from bir_extract import _compat
        if _compat.DB is None:
            return None
        if view is None:
            view = _active_view(doc)
        if view is None:
            return None
        count = (_compat.DB.FilteredElementCollector(doc, view.Id)
                 .WhereElementIsNotElementType().GetElementCount())
        mtime = 0
        try:
            path = doc.PathName
            if path and os.path.isfile(path):
                mtime = int(os.path.getmtime(path))
        except Exception:
            pass
        return {"elements": int(count), "file_mtime": mtime}
    except Exception:
        return None


def save_fingerprint(doc, cdir, view=None):
    if view is None:
        view = _active_view(doc)
    data = _view_meta(view) if view is not None else {}
    data.update(_model_fingerprint(doc, view) or {})
    if not data:
        return
    data["loaded_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        # UTF-8 safe: the view name may carry a non-ASCII char (see transport).
        from bir_contract.transport import write_json
        write_json(os.path.join(cdir, _FINGERPRINT_NAME), data)
    except Exception:
        pass


def _load_fingerprint(cdir):
    try:
        from bir_contract.transport import read_json
        data = read_json(os.path.join(cdir, _FINGERPRINT_NAME))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _fp_diff(old, new):
    """The model-content comparison shared by every staleness check."""
    if not old or not new:
        return None
    if old.get("elements") is not None and new.get("elements") is not None \
            and old.get("elements") != new.get("elements"):
        return ("the model has changed (%s elements now vs %s at Load)"
                % (new.get("elements"), old.get("elements")))
    if (old.get("file_mtime") and new.get("file_mtime")
            and old.get("file_mtime") != new.get("file_mtime")):
        return "the model file was saved since Load"
    return None


def staleness(doc, view=None):
    """-> None when a view's cache looks fresh (or freshness is unknowable),
    else a short human-readable reason it looks out of date."""
    cdir, bundle_ref, _blend = cache_paths(doc, view)
    if not os.path.isfile(bundle_ref):
        # Legacy per-doc slot: also compare the view name (the old single-slot
        # cache held whatever view was loaded last).
        root = bir_bootstrap.cache_dir_for(bir_bootstrap.doc_cache_key(doc))
        if not os.path.isfile(os.path.join(root, SCENE_SPEC_FILENAME)):
            return None
        old = _load_fingerprint(root)
        v = view if view is not None else _active_view(doc)
        if old and v is not None:
            try:
                if old.get("view") and old.get("view") != str(v.Name):
                    return ("the active view is '%s' but '%s' was loaded"
                            % (v.Name, old.get("view")))
            except Exception:
                pass
        return _fp_diff(old, _model_fingerprint(doc, view))
    return _fp_diff(_load_fingerprint(cdir), _model_fingerprint(doc, view))


def slot_staleness(doc, slot):
    """Staleness for one Views-list slot: 'view deleted' when its view is gone,
    else the fingerprint comparison against the live model. None = fresh."""
    view = resolve_view(doc, slot.get("view_uid"))
    if view is None and slot.get("view_uid"):
        return "the view no longer exists in the model"
    new = _model_fingerprint(doc, view) if view is not None else None
    return _fp_diff(_load_fingerprint(slot["cache_dir"]), new)
