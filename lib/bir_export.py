"""Shared Revit-side export: active 3D view (or demo) -> glTF bundle.

Used by Load Model (extraction) and by Render Loaded Model / Open Model (which read
the cache), so the extraction path is identical. IronPython 2.7 safe. The caller
passes the active doc (it holds __revit__) and a report(msg) callback for output.
"""
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
            view = revit_extract.active_3d_view(doc)
            if view is None:
                report("- active view isn't a 3D view -> using demo box "
                       "(open a 3D view to render the model)")
            else:
                report("- extracting the active 3D view...")
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
    return bundle_ref, blend_path
