"""Extraction orchestrator (IronPython 2.7 safe; guarded RevitAPI).

Assembles a schema-conformant spec_dict + MeshData[] from a Revit view by
delegating to geometry / materials / camera / sun. Emits the current contract
(bir_contract.transport.CONTRACT_VERSION - the single source of truth). Imports
cleanly outside Revit; the RevitAPI is only touched when the functions are
actually called with a live doc.
"""
import datetime

from bir_contract.transport import CONTRACT_VERSION, fit_resolution
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
    from bir_extract import geometry, materials, camera, sun, view_export, lights

    # WYSIWYG first: CustomExporter walks exactly what the view DISPLAYS (host +
    # links, all visibility rules). 3D views only; the collector walk stays as
    # the 2D path and the fallback when the exporter can't run.
    extracted = None
    try:
        if view_export.available() and isinstance(view, DB.View3D):
            extracted = view_export.extract_view(doc, view, progress=progress)
    except Exception:
        extracted = None
    if extracted is None:
        extracted = geometry.extract_geometry(doc, view, progress=progress)
    # extract_view returns lights (5-tuple); the collector fallback doesn't (4).
    light_refs = extracted[4] if len(extracted) > 4 else None
    meshes, elements, material_ids, link_docs = extracted[0], extracted[1], \
        extracted[2], extracted[3]
    mats = materials.extract_materials(doc, material_ids, link_docs)
    cam = camera.extract(doc, view)
    sn = sun.extract_sun(doc, view)
    lg = _extract_lights(doc, view, light_refs, lights)

    render = _render(render_overrides)
    asp = cam.get("crop_aspect")            # match the frame to the crop rectangle
    if asp:
        render["resolution"] = fit_resolution(render.get("resolution"), asp)

    spec = {
        "contract_version": CONTRACT_VERSION,
        "source": _source(doc, view),
        "units": {"source_unit": "feet", "scale_to_meters": 0.3048, "up_axis": "Z"},
        "coordinate_system": {"project_base_point": _base_point(doc),
                              "true_north_degrees": 0.0},
        "geometry": {"transport": "gltf", "uri": "scene.glb", "elements": elements},
        "materials": mats,
        "camera": cam,
        "sun": sn,
        "lights": lg,
        "world": {"sky_type": "nishita", "strength": 1.0,
                  "ground_albedo": [0.3, 0.3, 0.3],
                  # The model brings its own terrain (site link / toposolid):
                  # the Blender side then skips the artificial ground plane.
                  "has_site": _detect_site(elements)},
        "render": render,
    }
    return spec, meshes


def _extract_lights(doc, view, light_refs, lights):
    """Resolve OnLight captures to contract lights; fall back to the host
    collector when the exporter reported none (2D path, or a view whose lights
    the exporter didn't surface). Never fatal - a lighting failure just yields
    no lights, never a broken export. A concise log line per light is printed so
    the real photometric parameter names/units surface on the first live run."""
    log = []
    lg = []
    try:
        if light_refs:
            lg = lights.resolve_lights(light_refs, doc, log=log)
        if not lg:
            lg = lights.extract_lights_collector(doc, view, log=log)
    except Exception:
        lg = []
    try:
        if log:
            print("Blendit: extracted %d light(s):" % len(lg))
            for line in log:
                print("  " + line)
    except Exception:
        pass
    return lg


def _detect_site(elements):
    """True when the extraction carries real terrain: topography or a toposolid
    (host OR linked - view_export/geometry tag link elements with their real Revit
    category). Keyed off actual geometry, NOT a link's file name: a link merely
    named '...site...' with no terrain must still get the shadow-catcher ground, or
    the building floats."""
    try:
        for e in elements or []:
            cat = str(e.get("category", "")).lower()
            if "topograph" in cat or "toposolid" in cat:
                return True
    except Exception:
        pass
    return False


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
