"""Loaded 3D views keep their COMPOSED framing (frame="view") - bpy only.

    blender --background --python tests/headless_view_camera.py

The Revit side marks a 3D view's camera frame="view" (exact pose + fov from the
crop box). These checks lock the Blender half: the camera is placed AT the spec
eye with the spec fov - never auto-fitted - and the run overrides can't clobber
the projection or the crop aspect.
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import bpy  # noqa: E402
import mathutils  # noqa: E402

from blender.pipeline import camera as C  # noqa: E402
from blender.pipeline.run import _apply_overrides  # noqa: E402

SCALE = 0.3048
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print("  %-56s %s %s" % (name, "OK" if ok else "FAIL", detail))


def _fresh_scene_with_box():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new("box")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=6.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("box", mesh)
    bpy.context.scene.collection.objects.link(obj)


def _spec(cam):
    return {"camera": cam, "render": {"resolution": [1600, 900]}}


def main():
    # --- 1. perspective frame="view": exact eye + fov, no refit ---------------
    _fresh_scene_with_box()
    eye = [40.0, -60.0, 18.0]
    cam = {"type": "perspective", "frame": "view", "position": eye,
           "target": [0.0, 0.0, 8.0], "up": [0.0, 0.0, 1.0],
           "fov_degrees": 62.0, "crop_aspect": 1.25}
    cam_obj = C.setup_camera(_spec(cam), SCALE)
    want = mathutils.Vector([v * SCALE for v in eye])
    got = cam_obj.matrix_world.translation
    check("perspective view: camera AT the Revit eye (no dolly)",
          (got - want).length < 1e-5, str(tuple(round(v, 4) for v in got)))
    fwd = (cam_obj.matrix_world.to_quaternion()
           @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    want_fwd = (mathutils.Vector([0.0, 0.0, 8.0 * SCALE]) - want).normalized()
    check("perspective view: looks at the Revit target",
          (fwd - want_fwd).length < 1e-5)
    got_fov = math.degrees(cam_obj.data.angle)
    check("perspective view: fov honoured (62 deg)",
          abs(got_fov - 62.0) < 0.05, "%.2f" % got_fov)

    # --- 2. fit fallback unchanged: no frame -> auto-fit moves the camera -----
    _fresh_scene_with_box()
    fit = dict(cam)
    fit.pop("frame")
    cam_obj = C.setup_camera(_spec(fit), SCALE)
    moved = (cam_obj.matrix_world.translation - want).length > 0.1
    check("no frame field: auto-fit still reframes (old behaviour)", moved)

    # --- 3. ortho frame="view": exact pose + crop width -----------------------
    _fresh_scene_with_box()
    ocam = {"type": "orthographic", "frame": "view", "position": eye,
            "target": [0.0, 0.0, 8.0], "up": [0.0, 0.0, 1.0],
            "ortho_scale": 40.0, "crop_aspect": 1.333}
    cam_obj = C.setup_camera(_spec(ocam), SCALE)
    check("ortho view: camera AT the Revit eye",
          (cam_obj.matrix_world.translation - want).length < 1e-5)
    check("ortho view: ortho_scale = crop width (scale-true)",
          abs(cam_obj.data.ortho_scale - 40.0 * SCALE) < 1e-5,
          "%.4f" % cam_obj.data.ortho_scale)

    # --- 4. run overrides can't clobber an exact view -------------------------
    spec = _spec(dict(cam))
    _apply_overrides(spec, {"camera_type": "orthographic",
                            "resolution": [1920, 1080]})
    check("override guard: camera type stays perspective",
          spec["camera"].get("type") == "perspective")
    check("override guard: resolution refit to the crop aspect (1920x1536)",
          spec["render"]["resolution"] == [1920, 1536],
          str(spec["render"]["resolution"]))
    spec_fit = _spec(dict(fit))
    _apply_overrides(spec_fit, {"camera_type": "orthographic",
                                "resolution": [1920, 1080]})
    check("fit camera: overrides still apply as before",
          spec_fit["camera"]["type"] == "orthographic"
          and spec_fit["render"]["resolution"] == [1920, 1080])

    failed = [n for n, ok in CHECKS if not ok]
    print("VIEWCAM: %d checks, %d failed%s"
          % (len(CHECKS), len(failed), (" -> " + ", ".join(failed)) if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
