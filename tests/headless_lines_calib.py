"""Headless calibration on the real (lighter) cached model.

Run under Blender:
    blender --background --python tests/headless_lines_calib.py -- "<bundle scene_spec.json>"

Times the .blend-cache-free path (import + prepare), exercises the new Line Art
controls (crease / intersection / hidden-line / regenerate), and renders a small
linework PNG so we know lines work + roughly how heavy they are on this model.
"""
import os
import sys
import time

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _bundle_arg():
    argv = sys.argv
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    if extra:
        return extra[0]
    # default: the first local model cache slot (this is a perf/calibration tool on a
    # heavy real model - pass a bundle after `--`, or extract one first, to run it).
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "blendit", "cache")
    try:
        for name in sorted(os.listdir(root)):
            cand = os.path.join(root, name, "scene_spec.json")
            if os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return ""


def main():
    bundle = _bundle_arg()
    print("bundle:", bundle, "exists=", os.path.isfile(bundle))
    if not os.path.isfile(bundle):
        print("SKIP headless_lines_calib: no model bundle (pass one after `--`).")
        return

    from blender.pipeline.run import import_scene, prepare_scene
    from blender.pipeline.presets import get_preset
    from blender.pipeline import npr

    t0 = time.time()
    loaded, spec = import_scene(bundle, overrides={"camera_type": "perspective",
                                                   "mode": "white", "engine": "EEVEE"})
    t_import = time.time() - t0
    nobj = len([o for o in bpy.data.objects if o.type == "MESH"])
    print("import: %.1fs  mesh objects: %d" % (t_import, nobj))

    t0 = time.time()
    prepare_scene(loaded, spec)            # white
    print("prepare (white): %.1fs" % (time.time() - t0))

    # switch to linework (this builds Line Art)
    spec.setdefault("render", {})["mode"] = "linework"
    t0 = time.time()
    get_preset("linework")(loaded, spec)
    bpy.context.view_layer.update()
    print("apply linework (Line Art build): %.1fs" % (time.time() - t0))

    # exercise the new controls
    npr.set_line_art_crease(50.0)
    npr.set_line_art_intersection(True)
    npr.set_line_art_occlusion(True)
    cr = npr.get_line_art_crease_deg()
    print("crease readback: %.1f deg (set 50)" % (cr if cr is not None else -1))
    assert cr is not None and abs(cr - 50.0) < 1.0, "crease set/readback mismatch"

    m = npr._active_lineart_mod()
    assert m is not None, "no line art modifier"
    assert m.use_intersection is True, "intersection not set"
    assert m.use_multiple_levels is True, "hidden-line (occlusion) not set"
    print("controls OK: intersection=%s multiple_levels=%s level_end=%s"
          % (m.use_intersection, m.use_multiple_levels, m.level_end))

    t0 = time.time()
    npr.refresh_line_art()
    print("refresh_line_art: %.2fs" % (time.time() - t0))

    # small render to prove lines actually rasterize on this model
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 480, 270
    sc.render.image_settings.file_format = "PNG"
    out = os.path.join(_HERE, "_calib_linework.png")
    sc.render.filepath = out
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print("render 480x270 linework: %.1fs -> %s (%d bytes)"
          % (time.time() - t0, out, os.path.getsize(out) if os.path.isfile(out) else 0))
    assert os.path.isfile(out) and os.path.getsize(out) > 2000, "linework render too small"
    print("ALL OK")


main()
