"""Headless check: Line Art bake/cache freezes the trace and export reuses it.

    blender --background --python tests/headless_bake.py

Baking stores the procedural Line Art as real strokes and mutes the modifier so
export / render / capture stop re-tracing. Needs Blender.
"""
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _stored(gp):
    try:
        return len(gp.data.layers[0].frames[0].drawing.strokes)
    except Exception:
        return -1


def main():
    from blender.pipeline.run import build_scene
    from blender.pipeline import npr, vector_export

    out_dir = os.path.join(_ROOT, "out")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    build_scene(os.path.join(_ROOT, "tests", "fixtures"),
                overrides={"mode": "pen", "engine": "EEVEE",
                           "camera_type": "perspective"})
    gp = bpy.data.objects.get(npr._GP_NAME)
    assert gp is not None, "pen mode built no Line Art GP"
    m = npr._lineart_mod(gp)

    assert not npr.is_line_art_baked(), "should start un-baked (modifier live)"
    assert _stored(gp) == 0, "procedural Line Art should store no strokes when live"

    assert npr.bake_line_art(), "bake failed"
    assert npr.is_line_art_baked(), "should report baked"
    assert not m.show_viewport and not m.show_render, "modifier must be muted"
    n = _stored(gp)
    assert n > 0, "no baked strokes were stored"
    print("baked strokes:", n)

    # export reuses the baked strokes (no retrace) and still produces real geometry
    out = os.path.join(out_dir, "bake_test.svg")
    vector_export.export_vector(out, "svg")
    assert b"<path" in open(out, "rb").read(), "baked export has no stroke geometry"

    npr.unbake_line_art()
    assert not npr.is_line_art_baked(), "should be un-baked"
    assert m.show_viewport and m.show_render, "modifier should be live again"

    # a real Regenerate re-traces (refresh) before re-baking; that must not stack
    # duplicate strokes onto the previous bake.
    npr.refresh_line_art()
    assert npr.bake_line_art()
    n2 = _stored(gp)
    assert n2 == n, "re-bake stacked duplicates (%d vs %d)" % (n2, n)

    print("BAKE OK (strokes=%d, export reused baked, no dupes on re-bake)" % n)


if __name__ == "__main__":
    main()
