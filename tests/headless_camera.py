"""Headless check: camera projection + framing.

    blender --background --python tests/headless_camera.py

Verifies the three camera behaviours:
  * two-point ON levels the camera so EVERY vertical world edge projects to a
    vertical screen line (constant screen-x top vs bottom);
  * the faithful (two-point OFF) view is pitched, so off-axis verticals converge;
  * orthographic mode produces an ORTHO camera with a positive ortho_scale, and
    reframe_current() flips an existing camera's projection in place.

Needs Blender (uses world_to_camera_view for exact projection).
"""
import os
import sys

import bpy
import mathutils
from bpy_extras.object_utils import world_to_camera_view

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_FIX = os.path.join(_ROOT, "tests", "fixtures")


def _sync():
    # matrix_world is lazy: refresh it so projection reads the orientation we just set.
    bpy.context.view_layer.update()


def _vertical_edge_skew():
    """Max horizontal screen drift (|x_top - x_bottom|) over the four vertical edges
    of the scene bounding box. ~0 means verticals render vertical."""
    from blender.pipeline.camera import _scene_bbox
    scene = bpy.context.scene
    cam = scene.camera
    bb = _scene_bbox()
    assert bb is not None, "no geometry to measure"
    mn, mx = bb
    worst = 0.0
    for cx in (mn.x, mx.x):
        for cy in (mn.y, mx.y):
            bottom = world_to_camera_view(scene, cam, mathutils.Vector((cx, cy, mn.z)))
            top = world_to_camera_view(scene, cam, mathutils.Vector((cx, cy, mx.z)))
            worst = max(worst, abs(top.x - bottom.x))
    return worst


def _cam_forward():
    q = bpy.context.scene.camera.matrix_world.to_quaternion()
    return (q @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()


def main():
    from blender.pipeline.run import build_scene
    from blender.pipeline import camera as cam_mod

    # --- faithful (two-point off): off-axis verticals must converge ---------------
    build_scene(_FIX, overrides={"mode": "white", "engine": "EEVEE",
                                 "camera_type": "perspective", "two_point": False})
    _sync()
    skew_faithful = _vertical_edge_skew()
    assert skew_faithful > 0.02, (
        "faithful view should show converging verticals, skew=%.4f" % skew_faithful)
    print("faithful skew: %.4f (converges, expected)" % skew_faithful)

    # --- two-point on: camera level, every vertical stays vertical ----------------
    build_scene(_FIX, overrides={"mode": "white", "engine": "EEVEE",
                                 "camera_type": "perspective", "two_point": True})
    _sync()
    fwd = _cam_forward()
    assert abs(fwd.z) < 1e-3, "two-point camera not level, forward.z=%.5f" % fwd.z
    skew_2pt = _vertical_edge_skew()
    assert skew_2pt < 1e-3, "two-point verticals not vertical, skew=%.5f" % skew_2pt
    print("two-point skew: %.5f (vertical, level forward.z=%.5f)" % (skew_2pt, fwd.z))

    # --- orthographic: ORTHO camera, positive scale -------------------------------
    build_scene(_FIX, overrides={"mode": "white", "engine": "EEVEE",
                                 "camera_type": "orthographic"})
    cam = bpy.context.scene.camera
    assert cam.data.type == "ORTHO", "ortho mode did not set an ORTHO camera"
    assert cam.data.ortho_scale > 0.0, "ortho_scale not set"
    print("ortho: type=%s scale=%.2f" % (cam.data.type, cam.data.ortho_scale))

    # --- reframe_current flips an existing camera's projection in place -----------
    cam_mod.reframe_current(cam, ortho=False, two_point=False, aspect=16.0 / 9.0)
    assert cam.data.type == "PERSP", "reframe_current did not switch to PERSP"
    cam_mod.reframe_current(cam, ortho=True, two_point=False, aspect=16.0 / 9.0)
    assert cam.data.type == "ORTHO", "reframe_current did not switch to ORTHO"
    cam_mod.reframe_current(cam, ortho=False, two_point=True, aspect=16.0 / 9.0)
    _sync()
    assert abs(_cam_forward().z) < 1e-3, "reframe_current two-point not level"
    print("reframe_current: PERSP/ORTHO/two-point toggles OK")

    # --- the interactive wrapper: panel state drives the REAL camera --------------
    # This is the reported bug: in Open Model, picking Orthographic must change the
    # capture/render camera, not just the viewport navigation.
    import blender.interactive.live as live
    for cls in live._CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    bpy.types.Scene.bir = bpy.props.PointerProperty(type=live.BIR_Settings)
    build_scene(_FIX, overrides={"mode": "white", "engine": "EEVEE",
                                 "camera_type": "perspective"})
    st = bpy.context.scene.bir
    st.view_persp = "ORTHO"          # -> _update_view_persp -> _reapply_camera
    assert bpy.context.scene.camera.data.type == "ORTHO", (
        "interactive Orthographic did not reach the render camera")
    st.view_persp = "PERSP"
    st.two_point = True              # -> _update_camera -> _reapply_camera
    _sync()
    assert abs(_cam_forward().z) < 1e-3, "interactive Two-Point did not level the camera"
    print("interactive wrapper: Projection + Two-Point drive the real camera OK")

    print("CAMERA OK")


if __name__ == "__main__":
    main()
