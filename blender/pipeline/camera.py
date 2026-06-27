"""Pipeline step: place + frame the Blender camera.

Uses the Revit view's DIRECTION and up, but auto-fits the position / ortho-scale /
distance to the actual imported geometry's bounding box. The Revit view's own zoom
is unreliable for framing: the default {3D} view reports its section/site extent
(often the whole site), which would shrink the model to a dot. Auto-fitting to the
real geometry always frames the model nicely from the Revit view angle.

Positions are source units (feet) * scale_to_meters; the geometry was already
scaled to meters on import, so we fit in metres.
"""
import math

import bpy
import mathutils


def setup_camera(spec, scale):
    cspec = spec.get("camera", {})
    name = cspec.get("name", "RevitView")
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    pos = _vec(cspec.get("position", [0.0, 0.0, 0.0]), scale)
    target = _vec(cspec.get("target", [0.0, 1.0, 0.0]), scale)
    up = _dir(cspec.get("up", [0.0, 0.0, 1.0]))
    forward = (target - pos)
    if forward.length < 1e-9:
        forward = mathutils.Vector((0.0, 1.0, 0.0))
    forward.normalize()

    if str(cspec.get("type", "perspective")) == "orthographic":
        cam_data.type = "ORTHO"
    else:
        cam_data.type = "PERSP"
        cam_data.sensor_width = float(cspec.get("sensor_mm", 36.0))
        focal = cspec.get("focal_length_mm")
        if focal:
            cam_data.lens = float(focal)
        else:
            fov = math.radians(float(cspec.get("fov_degrees", 45.0)))
            cam_data.lens = (cam_data.sensor_width / 2.0) / math.tan(fov / 2.0)

    res = spec.get("render", {}).get("resolution", [1600, 900])
    aspect = (float(res[0]) / float(res[1])) if res[1] else 1.7778

    _frame_to_geometry(cam_obj, cam_data, forward, up, aspect, scale, cspec)

    cam_data.clip_start = max(0.01, float(cspec.get("clip_start", 0.1)) * scale)
    cam_data.clip_end = max(1000.0, float(cspec.get("clip_end", 10000.0)) * scale)
    # TODO (Phase 1): true two-point perspective (level + lens shift_y).
    return cam_obj


def _frame_to_geometry(cam_obj, cam_data, forward, up_hint, aspect, scale, cspec,
                       margin=1.12):
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

    if cam_data.type == "ORTHO":
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
