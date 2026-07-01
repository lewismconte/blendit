"""Phase 1 extraction orchestrator (IronPython 2.7 safe; guarded RevitAPI).

Assembles a schema-conformant spec_dict + MeshData[] from the active 3D view by
delegating to geometry / materials / camera / sun. Emits contract 0.1.0 (no
appearance_class yet). Imports cleanly outside Revit; the RevitAPI is only touched
when the functions are actually called with a live doc.
"""
import datetime

from bir_extract import _compat

DB = _compat.DB


def have_revit():
    return _compat.have_revit()


def active_3d_view(doc):
    """Return the active view if it's a renderable 3D view, else None."""
    if DB is None:
        return None
    try:
        v = doc.ActiveView
        if isinstance(v, DB.View3D) and not v.IsTemplate:
            return v
    except Exception:
        pass
    return None


def build_scene_spec(doc, view3d, render_overrides=None, progress=None):
    """-> (spec_dict, meshes). Geometry/materials/camera/sun from the 3D view.
    `progress(done, total)` is forwarded to the geometry pass for a progress bar."""
    from bir_extract import geometry, materials, camera, sun

    meshes, elements, material_ids = geometry.extract_geometry(
        doc, view3d, progress=progress)
    mats = materials.extract_materials(doc, material_ids)
    cam = camera.extract_camera(view3d)
    sn = sun.extract_sun(doc, view3d)

    spec = {
        "contract_version": "0.1.0",
        "source": _source(doc, view3d),
        "units": {"source_unit": "feet", "scale_to_meters": 0.3048, "up_axis": "Z"},
        "coordinate_system": {"project_base_point": _base_point(doc),
                              "true_north_degrees": 0.0},
        "geometry": {"transport": "gltf", "uri": "scene.glb", "elements": elements},
        "materials": mats,
        "camera": cam,
        "sun": sn,
        "world": {"sky_type": "nishita", "strength": 1.0,
                  "ground_albedo": [0.3, 0.3, 0.3]},
        "render": _render(render_overrides),
    }
    return spec, meshes


def _render(overrides):
    # EEVEE default for a snappy one-click render (real-time feel); switch to
    # CYCLES + more samples for finals.
    r = {"mode": "realistic", "engine": "EEVEE", "resolution": [1600, 900],
         "samples": 64, "denoise": True, "view_transform": "AgX", "exposure": 0.0}
    if overrides:
        r.update(overrides)
    return r


def _source(doc, view3d):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    ver = _safe(lambda: doc.Application.VersionNumber, "")
    title = _safe(lambda: doc.Title, "")
    name = _safe(lambda: view3d.Name, "")
    return {"app": "Revit", "app_version": ver, "document": title,
            "active_view": name, "exported_at": ts}


def _base_point(doc):
    try:
        bp = DB.BasePoint.GetProjectBasePoint(doc)
        p = bp.Position
        return [p.X, p.Y, p.Z]
    except Exception:
        return [0.0, 0.0, 0.0]


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
