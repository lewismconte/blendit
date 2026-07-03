"""2D drawings: orthographic plan / elevation posing, scale-true framing, and the
section cut - plus the live-panel wiring that drives them.

    blender --background --python tests/headless_drawing.py

Checks the pipeline math (camera.frame_ortho_drawing / apply_section_cut) with exact
projection via world_to_camera_view, then the interactive plumbing
(live._pose_drawing) so a paper size + scale really reach the render camera.
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
    bpy.context.view_layer.update()


def _ndc(p):
    return world_to_camera_view(bpy.context.scene, bpy.context.scene.camera, p)


def main():
    from blender.pipeline.run import build_scene
    from blender.pipeline import camera as cam_mod
    from blender.pipeline.camera import _scene_bbox

    build_scene(_FIX, overrides={"mode": "white", "engine": "EEVEE",
                                 "camera_type": "perspective"})
    cam = bpy.context.scene.camera
    # frame the BUILDING, not the ground plane (the drawing framing excludes it)
    bb = _scene_bbox(exclude=cam_mod._DRAWING_BBOX_EXCLUDE)
    assert bb is not None, "no geometry in the fixture"
    mn, mx = bb
    center = (mn + mx) * 0.5

    # --- PLAN (fit): ortho, looking straight down, North (+Y) up on the page ------
    # world_to_camera_view reads the aspect from scene.render, so match it to the
    # aspect we pass (in the live path _pose_drawing sets the resolution first).
    bpy.context.scene.render.resolution_x = 1500
    bpy.context.scene.render.resolution_y = 1000
    cam_mod.frame_ortho_drawing(cam, "plan", ortho_scale=None, aspect=1.5)
    _sync()
    assert cam.data.type == "ORTHO", "plan did not set an ORTHO camera"
    assert cam.data.sensor_fit == "HORIZONTAL", "sensor fit must be HORIZONTAL"
    fwd = (cam.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1))).normalized()
    assert fwd.z < -0.999, "plan camera not looking down, fwd=%r" % (tuple(fwd),)
    north = _ndc(center + mathutils.Vector((0.0, 1.0, 0.0)))
    south = _ndc(center + mathutils.Vector((0.0, -1.0, 0.0)))
    assert north.y > south.y, "North is not up on the plan (n=%.3f s=%.3f)" % (
        north.y, south.y)
    # the whole model sits on the sheet
    for c in (mn, mx):
        n = _ndc(c)
        assert -0.01 <= n.x <= 1.01 and -0.01 <= n.y <= 1.01, "plan clips the model"
    print("plan: ortho, looking down, North up, model framed OK")

    # --- NORTH elevation, scale-true: ortho_scale == world width across the page --
    scale_true = 84.1                       # A1 landscape (0.841 m) at 1:100
    bpy.context.scene.render.resolution_x = 4966
    bpy.context.scene.render.resolution_y = 3508
    cam_mod.frame_ortho_drawing(cam, "north", ortho_scale=scale_true, aspect=4966 / 3508.0)
    _sync()
    assert abs(cam.data.ortho_scale - scale_true) < 1e-3, (
        "scale-true ortho_scale not honoured: %.3f" % cam.data.ortho_scale)
    fwd = (cam.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1))).normalized()
    assert fwd.y < -0.999, "north elevation not looking south, fwd=%r" % (tuple(fwd),)
    right = mathutils.Vector((-1.0, 0.0, 0.0))               # page-right for 'north'
    xr = _ndc(center + right * (scale_true / 2.0)).x
    xl = _ndc(center - right * (scale_true / 2.0)).x
    assert abs(xr - 1.0) < 0.02 and abs(xl - 0.0) < 0.02, (
        "page width != ortho_scale (xl=%.3f xr=%.3f)" % (xl, xr))
    print("north: scale-true ortho_scale spans exactly the page width OK")

    # --- SECTION CUT drives the near clip -----------------------------------------
    cam_mod.frame_ortho_drawing(cam, "plan", ortho_scale=None, aspect=1.5)
    _sync()
    pos = cam.matrix_world.translation
    fwd = (cam.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1))).normalized()
    corners = [mathutils.Vector((x, y, z))
               for x in (mn.x, mx.x) for y in (mn.y, mx.y) for z in (mn.z, mx.z)]
    depths = [(c - pos).dot(fwd) for c in corners]
    near, far = min(depths), max(depths)

    cam_mod.apply_section_cut(cam, 0.0)     # cut off: nothing clipped
    assert cam.data.clip_start <= near + 1e-6, "cut-off still clips the model"
    cam_mod.apply_section_cut(cam, 0.5)     # slice halfway down
    cs = cam.data.clip_start
    assert near < cs < far, "section cut not between the faces (%.3f)" % cs
    print("section cut: clip_start slices between near (%.2f) and far (%.2f) OK" % (
        near, far))

    # --- LIVE WIRING: a paper size + scale reach the render camera ----------------
    import blender.interactive.live as live
    for cls in live._CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    bpy.types.Scene.bir = bpy.props.PointerProperty(type=live.BIR_Settings)
    build_scene(_FIX, overrides={"mode": "white", "engine": "EEVEE",
                                 "camera_type": "perspective"})
    live._LOADED = object()                 # _pose_drawing only needs a camera
    st = bpy.context.scene.bir
    st.drawing_paper = "A1"
    st.drawing_orient = "LANDSCAPE"
    st.drawing_scale = "1:100"
    st.drawing_dpi = "150"
    live._pose_drawing("north")
    _sync()
    sc = bpy.context.scene
    assert (sc.render.resolution_x, sc.render.resolution_y) == (4967, 3508), (
        "sheet resolution wrong: %dx%d" % (sc.render.resolution_x, sc.render.resolution_y))
    assert abs(sc.camera.data.ortho_scale - 84.1) < 1e-3, (
        "scale-true not applied via the panel: %.3f" % sc.camera.data.ortho_scale)
    assert sc.camera.data.type == "ORTHO", "panel pose did not switch to ORTHO"
    assert st.drawing_last == "north", "drawing_last not recorded"
    assert st.projection == "ORTHO", "View panel projection not synced to ORTHO"
    print("live wiring: A1 1:100 @150dpi -> 4967x3508 px, ortho_scale 84.1 OK")

    print("DRAWING OK")


if __name__ == "__main__":
    main()
