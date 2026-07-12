"""Artificial lights end-to-end: the bundle's `lights` -> functional lamps.

Run: blender --background --python tests/headless_lights.py

Asserts the fixture's two lights become a BIR_Lights collection with the right
lamp types/positions/colours, that the lit-mode default shows them and a drawing
mode hides them, that the master toggle works, and - the point of the feature -
that the lights actually brighten a render (lit-vs-unlit mean-luma delta).
"""
import os
import sys

import bpy
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_OUT_DIR = os.path.join(_ROOT, "out")


def _mean_luma(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        return float(px.reshape(-1, 4)[:, :3].mean())
    finally:
        bpy.data.images.remove(img)


def main():
    from blender.pipeline.run import build_scene
    from blender.pipeline import lights

    if not os.path.isdir(_OUT_DIR):
        os.makedirs(_OUT_DIR)
    bundle = os.path.join(_ROOT, "tests", "fixtures")

    # realistic (a default-ON mode) builds + shows the lamps
    build_scene(bundle, overrides={"mode": "realistic", "samples": 8,
                                   "resolution": [320, 180]})
    coll = bpy.data.collections.get("BIR_Lights")
    assert coll is not None, "BIR_Lights collection missing"
    objs = {o.name: o for o in coll.objects}
    assert len(objs) == 2, "expected 2 lamps, got %d" % len(objs)
    print("collection OK (%d lamps)" % len(objs))

    # types + placement (metres: source feet * 0.3048)
    kinds = sorted(o.data.type for o in coll.objects)
    assert kinds == ["POINT", "SPOT"], "lamp types %r" % kinds
    pt = next(o for o in coll.objects if o.data.type == "POINT")
    sp = next(o for o in coll.objects if o.data.type == "SPOT")
    assert abs(pt.location.z - 5.0 * 0.3048) < 1e-4, pt.location.z
    assert abs(sp.location.z - 9.0 * 0.3048) < 1e-4, sp.location.z
    assert sp.data.spot_size > 0.0 and sp.data.energy > 0.0
    # 2700K point is warmer (more red than blue) than the 4000K spot
    assert pt.data.color[0] > pt.data.color[2], "2700K should be warm"
    assert sp.data.color[0] >= sp.data.color[2]
    print("types/placement/colour OK")

    # visible in realistic
    assert not pt.hide_render, "lamps should be visible in realistic"
    assert lights.default_visible_for("realistic") is True
    assert lights.default_visible_for("linework") is False
    print("visible in realistic OK")

    # a drawing mode hides them by default (full prepare_scene gating path)
    build_scene(bundle, overrides={"mode": "linework", "samples": 8,
                                   "resolution": [320, 180]})
    coll = bpy.data.collections.get("BIR_Lights")
    assert coll is not None and len(coll.objects) == 2, "lamps lost on mode switch"
    assert all(o.hide_render for o in coll.objects), \
        "lamps should hide in a drawing mode by default"
    print("per-mode default gating OK")

    # master toggle (on the current linework scene)
    lights.set_lights_visible(True)
    assert not next(iter(coll.objects)).hide_render
    lights.set_lights_visible(False)
    assert next(iter(coll.objects)).hide_render
    print("master toggle OK")

    # back to realistic for the brightness + strength checks
    build_scene(bundle, overrides={"mode": "realistic", "samples": 8,
                                   "resolution": [320, 180]})
    coll = bpy.data.collections.get("BIR_Lights")
    pt = next(o for o in coll.objects if o.data.type == "POINT")

    # strength multiplier scales relative to a stable base
    base = pt.data.energy
    lights.set_lights_strength(2.0)
    assert abs(pt.data.energy - base * 2.0) < 1e-3
    lights.set_lights_strength(2.0)                       # idempotent, no compounding
    assert abs(pt.data.energy - base * 2.0) < 1e-3
    lights.set_lights_strength(1.0)
    print("strength multiplier OK")

    # the feature's whole point: lights brighten the render. Isolate the lamps
    # from the sun (the fixture is a closed box seen from OUTSIDE, so kill the
    # sun/sky and put the point lamp just outside the camera-facing -Y wall so
    # its contribution lands on visible geometry).
    from blender.pipeline.presets import _helpers
    sun = _helpers.sun_object()
    if sun is not None:
        sun.data.energy = 0.0
    _helpers.set_world_strength(0.0)
    pt.location = (5.0 * 0.3048, -3.0 * 0.3048, 6.0 * 0.3048)
    pt.data.energy = 300.0
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 320, 180
    sc.render.image_settings.file_format = "PNG"

    lights.set_lights_visible(True)
    lit = os.path.join(_OUT_DIR, "lights_on.png")
    sc.render.filepath = lit
    bpy.ops.render.render(write_still=True)
    lit_luma = _mean_luma(lit)

    lights.set_lights_visible(False)
    off = os.path.join(_OUT_DIR, "lights_off.png")
    sc.render.filepath = off
    bpy.ops.render.render(write_still=True)
    off_luma = _mean_luma(off)
    assert lit_luma > off_luma + 0.002, \
        "lights didn't brighten the render (on %.4f vs off %.4f)" % (lit_luma, off_luma)
    print("lit-vs-unlit OK (on %.4f > off %.4f)" % (lit_luma, off_luma))

    print("LIGHTS OK")


main()
