"""Pipeline step: place + frame the Blender camera.

Uses the Revit view's DIRECTION and up, but auto-fits the position / ortho-scale /
distance to the actual imported geometry's bounding box. The Revit view's own zoom
is unreliable for framing: the default {3D} view reports its section/site extent
(often the whole site), which would shrink the model to a dot. Auto-fitting to the
real geometry always frames the model nicely from the Revit view angle.

Positions are source units (feet) * scale_to_meters; the geometry was already
scaled to meters on import, so we fit in metres.

Two extras layer on top of the auto-fit:
  * **Two-point perspective** (opt-in) keeps verticals vertical. A camera whose
    optical axis is horizontal never converges verticals — the convergence in a
    normal shot comes purely from the pitch — so we simply LEVEL the view direction
    (drop its vertical component) before framing. The camera ends up level at the
    model's mid height, model centred, verticals parallel. Revit's own 3D view is
    NOT two-point, so this is a deliberate correction, off by default.
  * **Manual framing** — `framing_margin` (padding), `focal_length_mm` (lens),
    and `shift_x/shift_y` (lens shift: slides the frame without tilting, so it keeps
    verticals vertical). These are framing controls, not extracted from Revit.

`reframe_current()` re-applies all of this to an existing camera at its CURRENT
orientation, for the interactive Open Model toggles (which must preserve the angle
the user has navigated to).
"""
import math

import bpy
import mathutils

DEFAULT_MARGIN = 1.12


def setup_camera(spec, scale):
    cspec = spec.get("camera", {})
    name = cspec.get("name", "RevitView")
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    forward, up = _orientation(cspec, scale)
    ortho = _is_ortho(cspec)
    two_point = bool(cspec.get("two_point_perspective", False)) and not ortho
    aspect = _aspect(spec)
    margin = float(cspec.get("framing_margin", DEFAULT_MARGIN))

    _configure_lens(cam_data, cspec, ortho)

    if two_point:
        leveled = _level(forward)
        if leveled is not None:
            forward, up = leveled, mathutils.Vector((0.0, 0.0, 1.0))
        # else: looking (near) straight up/down — two-point undefined, keep the view.

    _frame_to_geometry(cam_obj, cam_data, forward, up, aspect, scale, cspec,
                       ortho=ortho, margin=margin)

    # Lens shift slides the frame without tilting, so it preserves two-point.
    cam_data.shift_x = float(cspec.get("shift_x", 0.0))
    cam_data.shift_y = float(cspec.get("shift_y", 0.0))

    cam_data.clip_start = max(0.01, float(cspec.get("clip_start", 0.1)) * scale)
    cam_data.clip_end = max(1000.0, float(cspec.get("clip_end", 10000.0)) * scale)
    return cam_obj


def reframe_current(cam_obj, ortho, two_point, aspect,
                    margin=DEFAULT_MARGIN, focal_mm=None, shift_x=0.0, shift_y=0.0):
    """Re-apply projection + framing to an EXISTING camera at its CURRENT orientation.

    Used by the interactive Open Model toggles, which must keep the angle the user
    has navigated to (rather than snapping back to the Revit view direction). Reuses
    the same framing core as setup_camera."""
    cam_data = cam_obj.data
    bpy.context.view_layer.update()   # matrix_world is lazy; read the true orientation
    q = cam_obj.matrix_world.to_quaternion()
    forward = (q @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()   # camera looks -Z
    up = (q @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()

    if ortho:
        cam_data.type = "ORTHO"
    else:
        cam_data.type = "PERSP"
        if focal_mm:
            cam_data.lens = float(focal_mm)

    if two_point and not ortho:
        leveled = _level(forward)
        if leveled is not None:
            forward, up = leveled, mathutils.Vector((0.0, 0.0, 1.0))

    _frame_to_geometry(cam_obj, cam_data, forward, up, aspect, 1.0, {},
                       ortho=ortho, margin=margin)
    cam_data.shift_x = float(shift_x)
    cam_data.shift_y = float(shift_y)
    return cam_obj


def _frame_to_geometry(cam_obj, cam_data, forward, up_hint, aspect, scale, cspec,
                       ortho=False, margin=DEFAULT_MARGIN):
    bb = _scene_bbox()
    if bb is None:
        cam_obj.location = _vec(cspec.get("position", [0.0, 0.0, 0.0]), scale)
        cam_obj.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()
        return
    mn, mx = bb
    center = (mn + mx) * 0.5

    right = forward.cross(up_hint)
    if right.length < 1e-9:
        right = forward.cross(mathutils.Vector((0.0, 0.0, 1.0)))
    if right.length < 1e-9:
        right = mathutils.Vector((1.0, 0.0, 0.0))
    right.normalize()
    true_up = right.cross(forward).normalized()

    corners = [mathutils.Vector((x, y, z))
               for x in (mn.x, mx.x) for y in (mn.y, mx.y) for z in (mn.z, mx.z)]
    ext_r = max(abs((c - center).dot(right)) for c in corners)      # half-width
    ext_u = max(abs((c - center).dot(true_up)) for c in corners)    # half-height
    ext_f = max(abs((c - center).dot(forward)) for c in corners)    # half-depth

    if ortho:
        # ortho_scale spans the larger viewport dimension (sensor_fit AUTO).
        cam_data.ortho_scale = max(2.0 * ext_r, 2.0 * ext_u * aspect) * margin
        dist = 2.0 * ext_f + 10.0  # parallel projection: distance only affects clipping
    else:
        hfov = cam_data.angle
        vfov = 2.0 * math.atan(math.tan(hfov / 2.0) / aspect)
        dist_w = ext_r / math.tan(hfov / 2.0) if hfov > 1e-6 else ext_r
        dist_h = ext_u / math.tan(vfov / 2.0) if vfov > 1e-6 else ext_u
        dist = max(dist_w, dist_h) * margin + ext_f

    cam_obj.location = center - forward * dist
    cam_obj.rotation_euler = (center - cam_obj.location).to_track_quat("-Z", "Y").to_euler()


def _orientation(cspec, scale):
    pos = _vec(cspec.get("position", [0.0, 0.0, 0.0]), scale)
    target = _vec(cspec.get("target", [0.0, 1.0, 0.0]), scale)
    up = _dir(cspec.get("up", [0.0, 0.0, 1.0]))
    forward = target - pos
    if forward.length < 1e-9:
        forward = mathutils.Vector((0.0, 1.0, 0.0))
    return forward.normalized(), up


def _is_ortho(cspec):
    return str(cspec.get("type", "perspective")) == "orthographic"


def _aspect(spec):
    res = spec.get("render", {}).get("resolution", [1600, 900])
    return (float(res[0]) / float(res[1])) if res[1] else 1.7778


def _level(forward):
    """`forward` with its vertical component removed (a horizontal optical axis), or
    None if the view looks (near) straight up/down, where two-point is undefined."""
    fl = mathutils.Vector((forward.x, forward.y, 0.0))
    if fl.length < 1e-3:
        return None
    return fl.normalized()


def _configure_lens(cam_data, cspec, ortho):
    if ortho:
        cam_data.type = "ORTHO"
        return
    cam_data.type = "PERSP"
    cam_data.sensor_width = float(cspec.get("sensor_mm", 36.0))
    focal = cspec.get("focal_length_mm")
    if focal:
        cam_data.lens = float(focal)
    else:
        fov = math.radians(float(cspec.get("fov_degrees", 45.0)))
        cam_data.lens = (cam_data.sensor_width / 2.0) / math.tan(fov / 2.0)


def _scene_bbox():
    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        found = True
        mw = obj.matrix_world
        for corner in obj.bound_box:
            w = mw @ mathutils.Vector((corner[0], corner[1], corner[2]))
            for i in range(3):
                if w[i] < mn[i]:
                    mn[i] = w[i]
                if w[i] > mx[i]:
                    mx[i] = w[i]
    if not found:
        return None
    return mathutils.Vector(mn), mathutils.Vector(mx)


def _vec(v, scale):
    return mathutils.Vector((float(v[0]) * scale, float(v[1]) * scale,
                             float(v[2]) * scale))


def _dir(v):
    d = mathutils.Vector((float(v[0]), float(v[1]), float(v[2])))
    if d.length < 1e-9:
        return mathutils.Vector((0.0, 0.0, 1.0))
    return d.normalized()
