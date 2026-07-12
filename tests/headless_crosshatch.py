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

    # --- material + TamUV on every model mesh; ground = white paper --------
    meshes = [o for o in bpy.data.objects
              if o.type == "MESH" and o.name.startswith("BIR_Mat_")]
    assert meshes, "no merged meshes found - fixture import changed?"
    for o in meshes:
        mats = [m.name for m in o.data.materials if m is not None]
        assert mats == [hatch_tam.MATERIAL], "%s materials: %r" % (o.name, mats)
        assert o.data.uv_layers.get(hatch_tam.UV_LAYER), \
            "%s missing %s" % (o.name, hatch_tam.UV_LAYER)
    ground = bpy.data.objects.get("BIR_Ground")
    if ground is not None:
        gmats = [m.name for m in ground.data.materials if m is not None]
        assert gmats == [hatch_tam.GROUND_MATERIAL], \
            "ground should be the shadow-only variant, got %r" % gmats
        assert ground.data.uv_layers.get(hatch_tam.UV_LAYER), \
            "ground missing %s (its cast shadow hatches)" % hatch_tam.UV_LAYER
    assert bpy.data.objects.get("BIR_LineArt") is not None, "Line Art missing"
    print("material + TamUV on %d meshes OK (ground = shadow-only)" % len(meshes))

    # --- strokes actually drawn (not the flat-grey OSL fallback) -----------
    ink = _luma(out)
    frac = _stroke_fraction(ink)
    assert 0.25 < ink.mean() < 0.97, "mean luma %.3f: black or blank" % ink.mean()
    assert frac > 0.015, \
        "stroke gradient fraction %.4f: looks like the flat-grey fallback " \
        "(OSL compile failed or strokes vanished)" % frac
    print("strokes present OK (gradient fraction %.3f)" % frac)

    # --- TamUV really reaches the render device ----------------------------
    # If the UV attribute export regresses (the getattribute trap), every
    # pixel samples texel (0,0) and uv_scale can no longer change the image.
    def _render_at_scale(scale, name):
        hatch_tam.set_crosshatch(uv_scale=scale)
        p = os.path.join(_OUT_DIR, name)
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        return _luma(p)

    a = _render_at_scale(0.5, "crosshatch_uv_a.png")
    b = _render_at_scale(3.0, "crosshatch_uv_b.png")
    hatch_tam.set_crosshatch(uv_scale=0.5)
    duv = float(np.abs(a - b).mean())
    assert duv > 0.005, \
        "uv_scale change altered nothing (diff %.5f): TamUV isn't reaching " \
        "the device - is the UV Map node still linked into UVIn?" % duv
    print("TamUV live on device OK (scale diff %.4f)" % duv)

    # --- cast shadows really trace (behavioral, like the UV check) ---------
    hatch_tam.set_crosshatch(shadows=False)
    sc.render.filepath = os.path.join(_OUT_DIR, "crosshatch_noshadow.png")
    bpy.ops.render.render(write_still=True)
    noshadow = _luma(sc.render.filepath)
    hatch_tam.set_crosshatch(shadows=True)
    dsh = float(np.abs(a - noshadow).mean())
    assert dsh > 0.002, \
        "cast-shadow toggle changed nothing (diff %.5f): OSL trace() dead?" % dsh
    print("cast shadows traced OK (toggle diff %.4f)" % dsh)

    # --- style switch re-renders differently -------------------------------
    hatch_tam.set_crosshatch(style="charcoal")
    out2 = os.path.join(_OUT_DIR, "crosshatch_fixture_charcoal.png")
    sc.render.filepath = out2
    bpy.ops.render.render(write_still=True)
    d = float(np.abs(ink - _luma(out2)).mean())
    assert d > 0.005, "charcoal switch changed nothing (diff %.5f)" % d
    print("style switch OK (diff %.4f)" % d)

    # --- artificial fixtures drive the hatch tone --------------------------
    # (1) the packed light-data EXR round-trips: each texel equals the lamp it
    # was written from (this is the de-risk spike - OSL reads exactly these).
    coll = bpy.data.collections.get("BIR_Lights")
    assert coll is not None and len(coll.objects) >= 2, \
        "fixture should carry its 2 Revit lamps in BIR_Lights"
    lpath, count = hatch_tam.write_light_exr((0.0, 0.0, 0.0))
    assert count == len(coll.objects), \
        "packed %d of %d lamps" % (count, len(coll.objects))
    ld = bpy.data.images.load(lpath, check_existing=False)
    try:
        assert tuple(ld.size) == (3 * count, 1), \
            "light EXR shape %r != (%d, 1)" % (tuple(ld.size), 3 * count)
        lpx = np.empty(3 * count * 4, dtype=np.float32)
        ld.pixels.foreach_get(lpx)
        lpx = lpx.reshape(3 * count, 4)      # one row: index by column
    finally:
        bpy.data.images.remove(ld)
    lamps = sorted(coll.objects,            # write_light_exr's nearest-first order
                   key=lambda o: o.matrix_world.translation.length_squared)
    for i, o in enumerate(lamps):
        wp = o.matrix_world.translation
        got = lpx[3 * i, :3]
        assert max(abs(got[0] - wp.x), abs(got[1] - wp.y),
                   abs(got[2] - wp.z)) < 1e-3, \
            "%s packed pos %r != world %r" % (o.name, tuple(got), tuple(wp))
        assert lpx[3 * i + 2, 0] > 0.0, "%s packed zero energy" % o.name
    print("light-data EXR round-trip OK (%d lamps packed)" % count)

    # (2) the OSL fixture loop RESPONDS: a bright lamp in front of a VISIBLE face
    # lightens its hatch. (The fixture's own lamps sit inside the closed box,
    # lighting only unseen inner faces - so add one facing the camera-side wall.)
    hatch_tam.set_crosshatch(style="ink", uv_scale=0.5, ambient=0.15,
                             threshold=False, shadows=True)
    hatch_tam.refresh_lights(strength=1.0, enabled=False)
    sc.render.filepath = os.path.join(_OUT_DIR, "crosshatch_unlit.png")
    bpy.ops.render.render(write_still=True)
    unlit = _luma(sc.render.filepath)

    probe_data = bpy.data.lights.new("BIR_Lights_probe", type="POINT")
    probe_data.energy = 2000.0
    probe = bpy.data.objects.new("BIR_Lights_probe", probe_data)
    probe.location = (1.5, -2.5, 1.5)    # metres: in front of the box's -Y face
    coll.objects.link(probe)
    # Evaluate the new lamp's transform BEFORE refresh_lights reads matrix_world -
    # a stale identity matrix would pack the probe at the origin (lighting nothing
    # the camera sees) and the delta would be a misleading zero.
    bpy.context.view_layer.update()
    hatch_tam.refresh_lights(strength=1.0, enabled=True)
    sc.render.filepath = os.path.join(_OUT_DIR, "crosshatch_lit.png")
    bpy.ops.render.render(write_still=True)
    lit = _luma(sc.render.filepath)

    hatch_tam.refresh_lights(strength=1.0, enabled=False)   # restore no fixtures
    bpy.data.objects.remove(probe, do_unlink=True)
    dlit = float(np.abs(unlit - lit).mean())
    assert dlit > 0.003, \
        "artificial-light toggle changed nothing (diff %.5f): the OSL fixture " \
        "loop or the light-data EXR read is dead" % dlit
    assert lit.mean() > unlit.mean(), \
        "fixtures should LIGHTEN the hatch (mean %.3f !> %.3f)" % \
        (lit.mean(), unlit.mean())
    print("fixtures drive hatch tone OK (lit diff %.4f)" % dlit)

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
