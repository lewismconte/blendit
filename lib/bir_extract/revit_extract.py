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


def active_view(doc):
    """Return the active view if Blendit can extract it - a 3D view OR a 2D plan /
    section / elevation - else None (templates, sheets, schedules, drafting, etc.).
    2D views load as orthographic drawings (see camera.extract_camera_2d)."""
    if DB is None:
        return None
    try:
        v = doc.ActiveView
        if v is None or v.IsTemplate:
            return None
        if isinstance(v, (DB.View3D, DB.ViewPlan, DB.ViewSection)):
            return v
    except Exception:
        pass
    return None


def build_scene_spec(doc, view, render_overrides=None, progress=None):
    """-> (spec_dict, meshes). Geometry/materials/camera/sun from the active view
    (3D or a 2D plan / section / elevation). `progress(done, total)` is forwarded to
    the geometry pass for a progress bar."""
    from bir_extract import geometry, materials, camera, sun

    meshes, elements, material_ids = geometry.extract_geometry(
        doc, view, progress=progress)
    mats = materials.extract_materials(doc, material_ids)
    cam = camera.extract(doc, view)
    sn = sun.extract_sun(doc, view)

    render = _render(render_overrides)
    asp = cam.get("crop_aspect")            # match the frame to the crop rectangle
    if asp:
        render["resolution"] = _fit_resolution(render.get("resolution"), asp)

    spec = {
        "contract_version": "0.1.0",
        "source": _source(doc, view),
        "units": {"source_unit": "feet", "scale_to_meters": 0.3048, "up_axis": "Z"},
        "coordinate_system": {"project_base_point": _base_point(doc),
                              "true_north_degrees": 0.0},
        "geometry": {"transport": "gltf", "uri": "scene.glb", "elements": elements},
        "materials": mats,
        "camera": cam,
        "sun": sn,
        "world": {"sky_type": "nishita", "strength": 1.0,
                  "ground_albedo": [0.3, 0.3, 0.3]},
        "render": render,
    }
    return spec, meshes


def _fit_resolution(res, aspect):
    """Keep the long edge, set the short edge from `aspect` (width/height)."""
    try:
        long_edge = max(int(res[0]), int(res[1]))
    except Exception:
        long_edge = 1600
    if aspect >= 1.0:
        return [long_edge, max(1, int(round(long_edge / aspect)))]
    return [max(1, int(round(long_edge * aspect))), long_edge]


def _render(overrides):
    # EEVEE default for a snappy one-click render (real-time feel); switch to
    # CYCLES + more samples for finals.
    r = {"mode": "realistic", "engine": "EEVEE", "resolution": [1600, 900],
         "samples": 64, "denoise": True, "view_transform": "AgX", "exposure": 0.0}
    if overrides:
        r.update(overrides)
    return r


def _source(doc, view):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    ver = _safe(lambda: doc.Application.VersionNumber, "")
    title = _safe(lambda: doc.Title, "")
    name = _safe(lambda: view.Name, "")
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
