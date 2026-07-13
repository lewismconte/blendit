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

`convert_projection()` changes an existing camera's projection IN PLACE (the
interactive Open View "Projection" dropdown: Perspective / Two-Point / Ortho),
preserving the user's composition instead of re-running the auto-fit.
"""
import math

import bpy
import mathutils
from bpy_extras.object_utils import world_to_camera_view

DEFAULT_MARGIN = 1.12

# Interactive projection modes (the Open View "Projection" dropdown).
PERSP = "PERSP"
TWO_POINT = "TWO_POINT"
ORTHO = "ORTHO"

# 2D drawing directions -> (view forward, page-up hint) in Blender world axes.
# Revit exports Z-up with +X = East, +Y = North, so a plan looks down -Z with
# North (+Y) at the top of the sheet, and an elevation is NAMED for the facade it
# faces: the "North" elevation shows the north-facing wall, viewed from the north
# looking south (forward = -Y), which puts East on the left and West on the right,
# the standard architectural convention.
DRAWING_DIRECTIONS = {
    "plan":    ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),   # look down, North up
    "ceiling": ((0.0, 0.0, 1.0),  (0.0, 1.0, 0.0)),   # look up  (reflected ceiling)
    "north":   ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),   # north-facing facade
    "south":   ((0.0, 1.0, 0.0),  (0.0, 0.0, 1.0)),
    "east":    ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),   # east-facing facade
    "west":    ((1.0, 0.0, 0.0),  (0.0, 0.0, 1.0)),
}

# The ground plane spans the whole site; a drawing must frame the BUILDING, so the
# 2D framing / cut excludes it from the bounding box (it still renders as a ground line).
_DRAWING_BBOX_EXCLUDE = ("BIR_Ground",)


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
    frame = str(cspec.get("frame", "fit"))
    # A view that carries its OWN reliable frame is reproduced exactly, never
    # auto-fitted: "crop" = a cropped 2D plan/section/elevation; "view" = a
    # composed 3D view (the user framed that shot in Revit - honour it).
    crop = ortho and frame in ("crop", "view")
    exact_persp = (not ortho) and frame == "view"

    _configure_lens(cam_data, cspec, ortho)

    if crop:
        _place_from_spec(cam_obj, cam_data, forward, up, scale, cspec)
    elif exact_persp:
        if two_point:
            # Level the optical axis but KEEP the standpoint (dollying would
            # change the composed shot more than the leveling fixes).
            leveled = _level(forward)
            if leveled is not None:
                forward, up = leveled, mathutils.Vector((0.0, 0.0, 1.0))
        pos = _vec(cspec.get("position", [0.0, 0.0, 0.0]), scale)
        _set_pose(cam_obj, pos, forward, up)
        # HORIZONTAL fit: fov_degrees is the crop's horizontal angle and the
        # extracted shifts are offset/width - keep both true in any orientation.
        cam_data.sensor_fit = "HORIZONTAL"
        cam_data.shift_x = float(cspec.get("shift_x", 0.0))
        cam_data.shift_y = float(cspec.get("shift_y", 0.0))
    else:
        if two_point:
            leveled = _level(forward)
            if leveled is not None:
                forward, up = leveled, mathutils.Vector((0.0, 0.0, 1.0))
            # else: looking (near) straight up/down — two-point undefined, keep view.
        _frame_to_geometry(cam_obj, cam_data, forward, up, aspect, scale, cspec,
                           ortho=ortho, margin=margin)
        # Lens shift slides the frame without tilting, so it preserves two-point.
        cam_data.shift_x = float(cspec.get("shift_x", 0.0))
        cam_data.shift_y = float(cspec.get("shift_y", 0.0))

    # A section cut (plan cut plane / section line) rides on the near clip.
    cut = cspec.get("cut_distance")
    if cut is not None:
        cam_data.clip_start = max(0.001, float(cut) * scale)
    else:
        cam_data.clip_start = max(0.01, float(cspec.get("clip_start", 0.1)) * scale)
    cam_data.clip_end = max(1000.0, float(cspec.get("clip_end", 10000.0)) * scale)
    return cam_obj


def _set_pose(cam_obj, pos, forward, up_hint):
    """Pose the camera at `pos` looking along `forward` with `up_hint`, from an
    explicit (right, up, back) basis - exact even looking straight down (where
    to_track_quat's up is degenerate) and roll-faithful to the source view."""
    right = forward.cross(up_hint)
    if right.length < 1e-9:
        right = forward.cross(mathutils.Vector((0.0, 0.0, 1.0)))
    if right.length < 1e-9:
        right = mathutils.Vector((1.0, 0.0, 0.0))
    right.normalize()
    true_up = right.cross(forward).normalized()
    rot = mathutils.Matrix((
        (right.x, true_up.x, -forward.x),
        (right.y, true_up.y, -forward.y),
        (right.z, true_up.z, -forward.z),
    )).to_4x4()
    cam_obj.matrix_world = mathutils.Matrix.Translation(pos) @ rot
    return right, true_up


def _place_from_spec(cam_obj, cam_data, forward, up_hint, scale, cspec):
    """Place an ORTHO camera from the spec's own pose + ortho_scale (a cropped 2D
    Revit view or a composed 3D ortho view), skipping the geometry auto-fit. Uses
    a HORIZONTAL sensor fit so ortho_scale spans the frame width (the crop
    rectangle's width)."""
    pos = _vec(cspec.get("position", [0.0, 0.0, 0.0]), scale)
    right, true_up = _set_pose(cam_obj, pos, forward, up_hint)
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.shift_x = 0.0
    cam_data.shift_y = 0.0
    os_ = cspec.get("ortho_scale")
    if os_:
        cam_data.ortho_scale = float(os_) * scale       # crop width, scale-true
    else:                                               # no crop size -> fit fallback
        bb = _scene_bbox(exclude=_DRAWING_BBOX_EXCLUDE)
        if bb is not None:
            mn, mx = bb
            center = (mn + mx) * 0.5
            corners = [mathutils.Vector((x, y, z))
                       for x in (mn.x, mx.x) for y in (mn.y, mx.y) for z in (mn.z, mx.z)]
            ext_r = max(abs((c - center).dot(right)) for c in corners)
            ext_u = max(abs((c - center).dot(true_up)) for c in corners)
            cam_data.ortho_scale = 2.0 * max(ext_r, ext_u) * DEFAULT_MARGIN


def convert_projection(cam_obj, mode, focal_mm=None, extra_shift=0.0):
    """Change an existing camera's projection IN PLACE for the interactive session.

    Unlike the initial auto-fit, this preserves the camera's position (and, for
    PERSP / ORTHO, its orientation), so the user's composition survives the switch:

      * PERSP     - plain perspective at the current pose.
      * TWO_POINT - keep the eye where it is, LEVEL the optical axis (so verticals
                    stay vertical) and apply a vertical lens shift to recompose the
                    model back into frame. The architect's tilt-shift, not a
                    fly-to-mid-height reframe.
      * ORTHO     - parallel projection at the current pose, scaled to match the
                    perspective's apparent size (no size jump on toggle).

    `focal_mm` (>0) sets the lens; `extra_shift` is an additional manual vertical
    lens shift layered on top.
    """
    bpy.context.view_layer.update()   # matrix_world is lazy; read the true pose
    cam_data = cam_obj.data
    q = cam_obj.matrix_world.to_quaternion()
    forward = (q @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    pos = cam_obj.matrix_world.translation.copy()

    bb = _scene_bbox()
    center = (bb[0] + bb[1]) * 0.5 if bb is not None else pos + forward * 10.0
    dist = max(0.1, (center - pos).dot(forward))   # distance to the subject

    if focal_mm:
        cam_data.type = "PERSP"        # a lens is only meaningful in perspective
        cam_data.lens = float(focal_mm)
    hfov = cam_data.angle              # perspective FOV (valid whatever the type)

    if mode == ORTHO:
        cam_data.type = "ORTHO"
        # ortho_scale spans the larger sensor dimension, same reference as
        # cam_data.angle, so matching the perspective frustum at the subject keeps
        # the apparent size across the toggle. Then shift to re-centre the model:
        # this keeps the pose (so it round-trips cleanly back to perspective) and
        # stays centred even from a levelled two-point pose that no longer points
        # straight at the model.
        cam_data.ortho_scale = 2.0 * dist * math.tan(hfov / 2.0)
        sx, sy = _recompose_shift(cam_obj, center, axes="xy")
        cam_data.shift_x = sx
        cam_data.shift_y = sy + float(extra_shift)
        return

    cam_data.type = "PERSP"
    if mode == TWO_POINT:
        leveled = _level(forward)
        if leveled is not None:
            cam_obj.rotation_euler = leveled.to_track_quat("-Z", "Y").to_euler()
            cam_data.shift_x = 0.0
            _sx, sy = _recompose_shift(cam_obj, center, axes="y")
            cam_data.shift_y = sy + float(extra_shift)
            return
        # near-vertical view: two-point is undefined, fall back to plain perspective.
    cam_data.shift_x = 0.0
    cam_data.shift_y = float(extra_shift)


def frame_ortho_drawing(cam_obj, direction, ortho_scale=None, aspect=1.0,
                        margin=DEFAULT_MARGIN):
    """Pose `cam_obj` as an orthographic architectural drawing looking from
    `direction` (a key in DRAWING_DIRECTIONS: plan / ceiling / north / south /
    east / west), framed on the scene bounding box.

    The camera is set to ORTHO with a HORIZONTAL sensor fit, so `ortho_scale`
    always spans the sheet's WIDTH. Pass `ortho_scale` to force a scale-true frame
    (world width the page covers, e.g. paper_width_m x scale_denominator); leave it
    None to auto-fit the model onto the page. `aspect` is render_x / render_y and is
    used to fit the model's height under the horizontal sensor. Clip planes are set
    to enclose the model; a section cut layers on top via apply_section_cut().
    Returns the camera object.
    """
    fwd_raw, up_raw = DRAWING_DIRECTIONS.get(direction, DRAWING_DIRECTIONS["plan"])
    forward = mathutils.Vector(fwd_raw).normalized()
    up_hint = mathutils.Vector(up_raw).normalized()
    cam_data = cam_obj.data
    cam_data.type = "ORTHO"
    cam_data.sensor_fit = "HORIZONTAL"      # ortho_scale spans the page WIDTH
    cam_data.shift_x = 0.0
    cam_data.shift_y = 0.0

    bb = _scene_bbox(exclude=_DRAWING_BBOX_EXCLUDE)
    if bb is None:
        cam_obj.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()
        if ortho_scale:
            cam_data.ortho_scale = float(ortho_scale)
        return cam_obj
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

    if ortho_scale:
        cam_data.ortho_scale = float(ortho_scale)
    else:
        # HORIZONTAL fit: width holds 2*ext_r; the visible height is
        # ortho_scale / aspect, which must hold 2*ext_u -> ortho_scale >= 2*ext_u*aspect.
        cam_data.ortho_scale = max(2.0 * ext_r, 2.0 * ext_u * aspect) * margin

    dist = 2.0 * ext_f + 10.0               # parallel: distance only sets clipping
    loc = center - forward * dist
    # Build the pose from the (right, up, back) basis so the page-up is exact even
    # for a plan (looking straight down, where to_track_quat's up is degenerate).
    rot = mathutils.Matrix((
        (right.x, true_up.x, -forward.x),
        (right.y, true_up.y, -forward.y),
        (right.z, true_up.z, -forward.z),
    )).to_4x4()
    cam_obj.matrix_world = mathutils.Matrix.Translation(loc) @ rot
    cam_data.clip_start = 0.001
    cam_data.clip_end = 2.0 * dist + 10.0
    return cam_obj


def apply_section_cut(cam_obj, t):
    """Slice an orthographic drawing with a cut plane perpendicular to the view,
    driven by the near clip. `t` in (0, 1] moves the cut from the near face (0, no
    cut) toward the far face (1, everything clipped) along the view axis; t <= 0 or
    None disables the cut and shows every edge. Recomputed from the camera's current
    pose + the scene bbox, so it stays correct after a re-fit. This is what turns an
    elevation into a section and a top view into a floor plan (probe-confirmed:
    silhouette of the clipped geometry == the cut line, interior edges below read
    as normal lines).
    """
    cam_data = cam_obj.data
    bb = _scene_bbox(exclude=_DRAWING_BBOX_EXCLUDE)
    if bb is None:
        return
    bpy.context.view_layer.update()         # matrix_world is lazy
    forward = (cam_obj.matrix_world.to_quaternion()
               @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    pos = cam_obj.matrix_world.translation
    mn, mx = bb
    corners = [mathutils.Vector((x, y, z))
               for x in (mn.x, mx.x) for y in (mn.y, mx.y) for z in (mn.z, mx.z)]
    ds = [(c - pos).dot(forward) for c in corners]
    near, far = min(ds), max(ds)
    if not t or t <= 0.0:
        cam_data.clip_start = max(0.001, near - 1.0)   # in front of everything
    else:
        cam_data.clip_start = max(0.001, near + float(t) * (far - near))
    cam_data.clip_end = far + 1.0


def _recompose_shift(cam_obj, target, axes="y"):
    """Lens shift(s) that re-centre `target` in frame. Exact and aspect-aware via
    world_to_camera_view; the projection is linear in each shift, so two samples
    solve it. Returns (shift_x, shift_y); only the requested axes are solved (the
    rest come back 0). Used to recompose after levelling (two-point, vertical only)
    and to re-centre orthographic (both axes)."""
    scene = bpy.context.scene
    cam_data = cam_obj.data
    cam_data.shift_x = 0.0
    cam_data.shift_y = 0.0
    bpy.context.view_layer.update()
    c0 = world_to_camera_view(scene, cam_obj, target)
    cam_data.shift_x = 0.1
    cam_data.shift_y = 0.1
    bpy.context.view_layer.update()
    c1 = world_to_camera_view(scene, cam_obj, target)
    cam_data.shift_x = 0.0
    cam_data.shift_y = 0.0
    sx = sy = 0.0
    if "x" in axes:
        slope = (c1.x - c0.x) / 0.1
        sx = (0.5 - c0.x) / slope if abs(slope) > 1e-6 else 0.0
    if "y" in axes:
        slope = (c1.y - c0.y) / 0.1
        sy = (0.5 - c0.y) / slope if abs(slope) > 1e-6 else 0.0
    return sx, sy


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


def _scene_bbox(exclude=None):
    """Bounding box of all MESH objects (world space). `exclude` is a set of object
    names to skip - the 2D drawing framing passes the ground plane so plans /
    elevations frame the building, not the (much larger) ground."""
    exclude = exclude or ()
    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.name in exclude:
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
