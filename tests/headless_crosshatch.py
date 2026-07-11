"""Crosshatch mode end-to-end: the OSL TAM material renders headless.

Run: blender --background --python tests/headless_crosshatch.py

Covers the mode's three integration risks:
  * the pre-compiled template material + EXTERNAL .osl actually renders in
    --background (socket creation is a GUI-only operator, so a regression
    here would ship black/blank renders from Revit);
  * STROKES are present - not the flat-grey fallback Cycles paints when the
    OSL compile or the TamUV attribute export fails. Plain mean/std pixel
    stats cannot tell those apart (found the hard way), so the assert is on
    HIGH-FREQUENCY gradient energy, which only real strokes produce;
  * engine flags derive from the mode (no leakage): a realistic re-apply
    must switch shading_system back off and denoising back on.
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
_THRESHOLD = 2000        # bytes: a real render of the fixture is far bigger


def _luma(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        return px.reshape(h, w, 4)[:, :, :3].mean(axis=2)
    finally:
        bpy.data.images.remove(img)


def _stroke_fraction(luma):
    """Fraction of pixels sitting on a strong horizontal gradient. Hatching
    strokes cover surfaces with them; outlines alone (or the flat-grey OSL
    failure) concentrate them on a handful of edge pixels."""
    grad = np.abs(np.diff(luma, axis=1))
    return float((grad > 0.1).mean())


def main():
    from blender.pipeline.run import run_pipeline
    from blender.pipeline import hatch_tam
    from blender.pipeline.engine import setup_engine

    bundle = os.path.join(_ROOT, "tests", "fixtures")
    if not os.path.isdir(_OUT_DIR):
        os.makedirs(_OUT_DIR)
    out = os.path.join(_OUT_DIR, "crosshatch_fixture.png")
    if os.path.isfile(out):
        os.remove(out)

    run_pipeline(bundle, out, overrides={
        "mode": "crosshatch", "samples": 8, "resolution": [480, 270],
    })
    assert os.path.isfile(out) and os.path.getsize(out) >= _THRESHOLD, \
        "crosshatch render missing or trivially small"
    print("render OK (%d bytes)" % os.path.getsize(out))

    # --- engine flags derived from the mode --------------------------------
    sc = bpy.context.scene
    assert sc.render.engine == "CYCLES", sc.render.engine
    assert sc.cycles.shading_system is True, "OSL shading system not enabled"
    assert sc.cycles.device == "CPU", sc.cycles.device
    assert sc.cycles.use_denoising is False, "denoising would smear strokes"
    print("engine flags OK")

    # --- material + TamUV on every mesh (and the ground, if any) -----------
    meshes = [o for o in bpy.data.objects
              if o.type == "MESH" and (o.name.startswith("BIR_Mat_")
                                       or o.name == "BIR_Ground")]
    assert meshes, "no merged meshes found - fixture import changed?"
    for o in meshes:
        mats = [m.name for m in o.data.materials if m is not None]
        assert mats == [hatch_tam.MATERIAL], "%s materials: %r" % (o.name, mats)
        assert o.data.uv_layers.get(hatch_tam.UV_LAYER), \
            "%s missing %s" % (o.name, hatch_tam.UV_LAYER)
    assert bpy.data.objects.get("BIR_LineArt") is not None, "Line Art missing"
    print("material + TamUV on %d meshes OK" % len(meshes))

    # --- strokes actually drawn (not the flat-grey OSL fallback) -----------
    ink = _luma(out)
    frac = _stroke_fraction(ink)
    assert 0.25 < ink.mean() < 0.97, "mean luma %.3f: black or blank" % ink.mean()
    assert frac > 0.03, \
        "stroke gradient fraction %.4f: looks like the flat-grey fallback " \
        "(OSL compile failed or TamUV wasn't exported to the device)" % frac
    print("strokes present OK (gradient fraction %.3f)" % frac)

    # --- style switch re-renders differently -------------------------------
    hatch_tam.set_crosshatch(style="charcoal")
    out2 = os.path.join(_OUT_DIR, "crosshatch_fixture_charcoal.png")
    sc.render.filepath = out2
    bpy.ops.render.render(write_still=True)
    d = float(np.abs(ink - _luma(out2)).mean())
    assert d > 0.005, "charcoal switch changed nothing (diff %.5f)" % d
    print("style switch OK (diff %.4f)" % d)

    # --- mode round-trip: flags self-heal (the shared-spec leak regression).
    # setup_engine derives shading_system/device/denoise from render.mode, so
    # a realistic re-apply must undo every crosshatch flag WITHOUT the spec
    # carrying any cleanup keys.
    setup_engine({"render": {"mode": "realistic", "engine": "CYCLES"}})
    assert sc.cycles.shading_system is False, "OSL leaked into realistic"
    assert sc.cycles.use_denoising is True, "denoise-off leaked into realistic"
    print("mode round-trip flags OK")

    print("CROSSHATCH OK")


main()
