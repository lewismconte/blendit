"""Active 3D view camera -> contract `camera` dict (feet, Z-up).

Position + look direction come straight from the view orientation (the important
part); the focal point is placed along the forward direction at the distance to
the view's bounding-box centre. Exact perspective FOV isn't cleanly exposed by the
Revit API, so we use a sane architectural default for now (TODO: derive precisely
from the crop region).
"""
from extract import _compat

DB = _compat.DB


def extract_camera(view3d):
    cam = {
        "name": _name(view3d), "type": "perspective",
        "position": [0.0, 0.0, 0.0], "target": [0.0, 1.0, 0.0],
        "up": [0.0, 0.0, 1.0], "fov_degrees": 50.0,
        "two_point_perspective": True,
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
