"""Shared Revit-side export: active 3D view (or demo) -> glTF bundle.

Used by Load Model (extraction) and by Render Loaded Model / Open Model (which read
the cache), so the extraction path is identical. IronPython 2.7 safe. The caller
passes the active doc (it holds __revit__) and a report(msg) callback for output.
"""
import json
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


def extract_or_demo(doc, cfg, report, progress=None):
    """-> (spec_dict, meshes). Real active-3D-view extraction, demo box fallback."""
    overrides = _render_overrides(cfg)
    if doc is None:
        report("- no active Revit document -> using demo box")
    else:
        try:
            from bir_extract import revit_extract
            view = revit_extract.active_view(doc)
            if view is None:
                report("- active view can't be loaded -> using demo box "
                       "(open a 3D, plan, section or elevation view)")
            else:
                report("- extracting the active view...")
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


def export_bundle(doc, cfg, report, progress=None, out_dir=None):
    """-> (bundle_ref, out_dir). Extract + write the glTF bundle. `out_dir` lets
    callers (Load Model) target the model cache instead of the render folder."""
    spec, meshes = extract_or_demo(doc, cfg, report, progress=progress)
    report("- writing the glTF bundle...")
    if out_dir is None:
        out_dir = cfg.get("output_dir") or bir_bootstrap.default_output_dir()
    bundle_ref = get_exporter("gltf").export(spec, meshes, out_dir)
    return bundle_ref, out_dir


def export_bundle_with_progress(doc, cfg, report, out_dir=None):
    """export_bundle wrapped in a pyRevit progress bar when available (the
    extraction over thousands of elements is the main wait). Falls back to a
    plain export if pyRevit forms aren't available."""
    try:
        from pyrevit import forms
    except Exception:
        forms = None
    if forms is None:
        return export_bundle(doc, cfg, report, out_dir=out_dir)

    title = "Blendit - extracting model... ({value} of {max_value})"
    with forms.ProgressBar(title=title) as pb:
        def progress(done, total):
            try:
                pb.update_progress(done, total)
            except Exception:
                pass
        return export_bundle(doc, cfg, report, progress=progress, out_dir=out_dir)


# --- model cache --------------------------------------------------------------
def cache_paths(doc):
    """-> (cache_dir, bundle_ref, blend_path) for this document. The bundle_ref is
    the sidecar scene_spec.json path; the .blend is the prepared-scene cache."""
    key = bir_bootstrap.doc_cache_key(doc)
    cdir = bir_bootstrap.cache_dir_for(key)
    return (cdir,
            os.path.join(cdir, SCENE_SPEC_FILENAME),
            os.path.join(cdir, _BLEND_NAME))


def cached_bundle(doc):
    """-> (bundle_ref, blend_path) if a cached extraction exists for this doc,
    else (None, blend_path). blend_path may not exist yet (built on first open)."""
    cdir, bundle_ref, blend_path = cache_paths(doc)
    if os.path.isfile(bundle_ref):
        return bundle_ref, blend_path
    return None, blend_path


def refresh_cache(doc, cfg, report):
    """Re-extract the active view into this doc's cache slot and invalidate the
    stale prepared .blend (geometry changed). -> (bundle_ref, blend_path)."""
    cdir, bundle_ref, blend_path = cache_paths(doc)
    bundle_ref, _ = export_bundle_with_progress(doc, cfg, report, out_dir=cdir)
    try:
        if os.path.isfile(blend_path):
            os.remove(blend_path)  # the .blend no longer matches the geometry
    except Exception:
        pass
    save_fingerprint(doc, cdir)    # remember what the model looked like at Load
    return bundle_ref, blend_path


# --- staleness fingerprint ------------------------------------------------
# Saved at Load Model time so Open Model / Render Loaded Model can warn when the
# cached extraction no longer matches the model ("why is my new wall missing?").
# Deliberately cheap and approximate: view name + visible element count + the
# model file's mtime. A soft signal, never a blocker.
_FINGERPRINT_NAME = "fingerprint.json"


def _model_fingerprint(doc):
    """-> {view, elements, file_mtime} for the CURRENT model state, or None when
    it can't be computed (no doc / unsupported view / headless)."""
    if doc is None:
        return None
    try:
        from bir_extract import revit_extract, _compat
        if _compat.DB is None:
            return None
        view = revit_extract.active_view(doc)
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
        return {"view": str(view.Name), "elements": int(count),
                "file_mtime": mtime}
    except Exception:
        return None


def save_fingerprint(doc, cdir):
    fp = _model_fingerprint(doc)
    if fp is None:
        return
    try:
        f = open(os.path.join(cdir, _FINGERPRINT_NAME), "w")
        try:
            json.dump(fp, f, indent=2)
        finally:
            f.close()
    except Exception:
        pass


def _load_fingerprint(cdir):
    try:
        f = open(os.path.join(cdir, _FINGERPRINT_NAME))
        try:
            data = json.load(f)
        finally:
            f.close()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def staleness(doc):
    """-> None when the cache looks fresh (or freshness is unknowable), else a
    short human-readable reason it looks out of date."""
    cdir, bundle_ref, _blend = cache_paths(doc)
    if not os.path.isfile(bundle_ref):
        return None
    old = _load_fingerprint(cdir)
    new = _model_fingerprint(doc)
    if not old or not new:
        return None
    if old.get("view") != new.get("view"):
        return ("the active view is '%s' but '%s' was loaded"
                % (new.get("view"), old.get("view")))
    if old.get("elements") != new.get("elements"):
        return ("the model has changed (%s elements now vs %s at Load)"
                % (new.get("elements"), old.get("elements")))
    if (old.get("file_mtime") and new.get("file_mtime")
            and old.get("file_mtime") != new.get("file_mtime")):
        return "the model file was saved since Load"
    return None
