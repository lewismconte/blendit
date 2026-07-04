"""Active view camera -> contract `camera` dict (feet, Z-up).

3D views: position + look direction come straight from the view orientation (the
important part); the focal point is placed along the forward direction at the
distance to the view's bounding-box centre. Exact perspective FOV isn't cleanly
exposed by the Revit API, so we use a sane architectural default for now.

2D views (plan / section / elevation): an ORTHOGRAPHIC camera looking along
-ViewDirection, framed to the crop rectangle (frame="crop", so Blender honours the
crop instead of auto-fitting), carrying a `cut_distance` for the plan's view-range
cut plane or a section's cut line. Elevations carry no cut (show the whole facade).
Everything here is guarded: a failed Revit lookup falls back to a plain ortho fit,
never an exception that would abort the extraction.
"""
from bir_extract import _compat

DB = _compat.DB


def extract(doc, view):
    """Camera dict for any supported view: 3D (perspective / ortho) or a 2D plan /
    section / elevation (orthographic, crop-framed, with a cut plane)."""
    try:
        if DB is not None and isinstance(view, DB.View3D):
            return extract_camera(view)
    except Exception:
        pass
    return extract_camera_2d(doc, view)


def extract_camera(view3d):
    cam = {
        "name": _name(view3d), "type": "perspective",
        "position": [0.0, 0.0, 0.0], "target": [0.0, 1.0, 0.0],
        "up": [0.0, 0.0, 1.0], "fov_degrees": 50.0,
        # Off by default: stay faithful to the Revit view angle. Two-point is an
        # opt-in correction the user turns on in Open Model / Settings.
        "two_point_perspective": False,
    }
    try:
        o = view3d.GetOrientation()
        eye, fwd, up = o.EyePosition, o.ForwardDirection, o.UpDirection
        dist = _focal_distance(view3d, eye, fwd)
        cam["position"] = [eye.X, eye.Y, eye.Z]
        cam["target"] = [eye.X + fwd.X * dist, eye.Y + fwd.Y * dist,
                         eye.Z + fwd.Z * dist]
        cam["up"] = [up.X, up.Y, up.Z]
    except Exception:
        pass

    try:
        if not view3d.IsPerspective:
            cam["type"] = "orthographic"
            cam["ortho_scale"] = _ortho_scale(view3d)
    except Exception:
        pass
    return cam


def _name(view3d):
    try:
        return view3d.Name
    except Exception:
        return "RevitView"


def _bbox(view3d):
    try:
        return view3d.get_BoundingBox(None)
    except Exception:
        return None


def _focal_distance(view3d, eye, fwd):
    bb = _bbox(view3d)
    if bb is not None:
        cx = (bb.Min.X + bb.Max.X) / 2.0
        cy = (bb.Min.Y + bb.Max.Y) / 2.0
        cz = (bb.Min.Z + bb.Max.Z) / 2.0
        d = (cx - eye.X) * fwd.X + (cy - eye.Y) * fwd.Y + (cz - eye.Z) * fwd.Z
        if d > 1.0:
            return d
    return 50.0


def _ortho_scale(view3d):
    bb = _bbox(view3d)
    if bb is not None:
        dx = bb.Max.X - bb.Min.X
        dy = bb.Max.Y - bb.Min.Y
        dz = bb.Max.Z - bb.Min.Z
        return max(dx, dy, dz)
    return 100.0


# --- 2D views (plan / section / elevation) ----------------------------------

def extract_camera_2d(doc, view):
    """Orthographic camera from a 2D view. Looks along -ViewDirection, frames the
    crop rectangle (falls back to the view's model bbox), and carries the cut plane
    so Blender slices a plan / section. Never raises."""
    cam = {"name": _name(view), "type": "orthographic", "frame": "crop",
           "position": [0.0, 0.0, 0.0], "target": [0.0, 1.0, 0.0],
           "up": [0.0, 0.0, 1.0], "two_point_perspective": False,
           "view_kind": view_kind(view)}
    try:
        vd = view.ViewDirection.Normalize()        # points OUT of screen (to viewer)
        up = view.UpDirection.Normalize()
        right = view.RightDirection.Normalize()
    except Exception:
        return cam
    fwd = vd.Negate()                              # the camera look direction

    frame = _crop_frame(view)
    if frame is None:
        frame = _bbox_frame(view, right, up, vd)
    if frame is None:
        return cam
    center, width, height, depth = frame

    pad = _pad(depth)
    eye = center.Add(vd.Multiply(depth * 0.5 + pad))   # in front of the frame
    cam["position"] = [eye.X, eye.Y, eye.Z]
    cam["target"] = [center.X, center.Y, center.Z]
    cam["up"] = [up.X, up.Y, up.Z]
    if width and width > 1e-6:
        cam["ortho_scale"] = float(width)          # crop WIDTH (HORIZONTAL fit)
    elif height and height > 1e-6:
        cam["ortho_scale"] = float(height)
    asp = _safe_aspect(width, height)
    if asp is not None:
        cam["crop_aspect"] = asp

    cut_pt = _cut_point(doc, view, center, depth, vd)
    if cut_pt is not None:
        try:
            cut_dist = cut_pt.Subtract(eye).DotProduct(fwd)
            if cut_dist and cut_dist > 1e-6:
                cam["cut_distance"] = float(cut_dist)
        except Exception:
            pass

    sc = _view_scale(view)
    if sc:
        cam["scale_denominator"] = sc
    return cam


def crop_aspect(view):
    """width/height of the active crop rectangle (for matching the render aspect)."""
    frame = _crop_frame(view)
    if frame is None:
        return None
    _c, w, h, _d = frame
    return _safe_aspect(w, h)


def view_kind(view):
    try:
        vt = view.ViewType
        if vt in (DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan,
                  DB.ViewType.EngineeringPlan, DB.ViewType.AreaPlan):
            return "plan"
        if vt == DB.ViewType.Section:
            return "section"
        if vt == DB.ViewType.Elevation:
            return "elevation"
        if vt == DB.ViewType.ThreeD:
            return "3d"
    except Exception:
        pass
    return "other"


def _crop_frame(view):
    """(center_world, width, height, depth) of the active crop box, or None. Width
    is along RightDirection, height along UpDirection, depth along ViewDirection."""
    try:
        if not view.CropBoxActive:
            return None
        cb = view.CropBox
        t = cb.Transform
        mn, mx = cb.Min, cb.Max
        mid = DB.XYZ((mn.X + mx.X) / 2.0, (mn.Y + mx.Y) / 2.0, (mn.Z + mx.Z) / 2.0)
        center = t.OfPoint(mid)
        return center, (mx.X - mn.X), (mx.Y - mn.Y), (mx.Z - mn.Z)
    except Exception:
        return None


def _bbox_frame(view, right, up, vd):
    """Fallback frame from the view's model bbox, measured along the view axes."""
    try:
        bb = view.get_BoundingBox(None)
        if bb is None:
            return None
        mn, mx = bb.Min, bb.Max
        center = DB.XYZ((mn.X + mx.X) / 2.0, (mn.Y + mx.Y) / 2.0, (mn.Z + mx.Z) / 2.0)
        corners = [DB.XYZ(x, y, z) for x in (mn.X, mx.X)
                   for y in (mn.Y, mx.Y) for z in (mn.Z, mx.Z)]
        wr = max([abs(c.Subtract(center).DotProduct(right)) for c in corners])
        hu = max([abs(c.Subtract(center).DotProduct(up)) for c in corners])
        df = max([abs(c.Subtract(center).DotProduct(vd)) for c in corners])
        return center, 2.0 * wr, 2.0 * hu, 2.0 * df
    except Exception:
        return None


def _cut_point(doc, view, center, depth, vd):
    """A world point on the cut plane, or None (elevations / unknowns: no cut).
    Plans cut at the view-range cut plane; sections cut at the section line (the
    front face of the crop, toward the viewer)."""
    kind = view_kind(view)
    if kind == "plan":
        z = _plan_cut_elevation(doc, view)
        if z is None:
            return None
        try:
            return DB.XYZ(center.X, center.Y, float(z))
        except Exception:
            return None
    if kind == "section":
        try:
            return center.Add(vd.Multiply(depth * 0.5))
        except Exception:
            return None
    return None


def _plan_cut_elevation(doc, view):
    """World Z of a plan's view-range cut plane (level elevation + cut offset)."""
    try:
        vr = view.GetViewRange()
        lid = vr.GetLevelId(DB.PlanViewPlane.CutPlane)
        off = vr.GetOffset(DB.PlanViewPlane.CutPlane)
        base = 0.0
        if lid is not None and lid != DB.ElementId.InvalidElementId:
            lvl = doc.GetElement(lid)
            if lvl is not None:
                try:
                    base = float(lvl.ProjectElevation)
                except Exception:
                    try:
                        base = float(lvl.Elevation)
                    except Exception:
                        base = 0.0
        return base + float(off)
    except Exception:
        return None


def _pad(depth):
    try:
        return max(float(depth), 10.0)
    except Exception:
        return 10.0


def _view_scale(view):
    try:
        s = int(view.Scale)
        return s if s > 0 else None
    except Exception:
        return None


def _safe_aspect(width, height):
    try:
        if width and height and float(height) > 1e-6:
            return float(width) / float(height)
    except Exception:
        pass
    return None
