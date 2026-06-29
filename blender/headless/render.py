"""Headless bpy entry point.

    blender --background --python blender/headless/render.py -- \
        --bundle "<scene_spec.json or bundle dir>" --out "<output.png>" \
        [--engine CYCLES|EEVEE] [--mode MODE] [--samples N] [--camera persp|ortho]

MODE is one of: realistic, white, shadow, specular, linework, pen, sketch, cel, hatch.

Args after `--` are ours; everything before is Blender's. CLI flags override the
SceneSpec's render settings, so the same bundle can be re-rendered in any mode /
engine without re-exporting from Revit.
"""
import argparse
import os
import sys


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def _parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="blendit", description=__doc__)
    p.add_argument("--bundle", required=True,
                   help="path to scene_spec.json or the bundle directory")
    p.add_argument("--out", required=True, help="output PNG path")
    p.add_argument("--engine", choices=["CYCLES", "EEVEE"])
    p.add_argument("--mode",
                   choices=["realistic", "white", "shadow", "linework", "specular",
                            "pen", "sketch", "cel", "hatch"])
    p.add_argument("--samples", type=int)
    p.add_argument("--camera", choices=["perspective", "orthographic"],
                   help="override the view's camera type")
    p.add_argument("--vector", choices=["svg", "pdf"],
                   help="export the line work as scalable SVG / PDF instead of a "
                        "raster (needs a line mode: linework/pen/sketch/cel)")
    p.add_argument("--open", action="store_true",
                   help="open the result when done (so the launcher needn't wait)")
    return p.parse_args(args)


_LINE_MODES = ("linework", "pen", "sketch", "cel", "hatch")


def main():
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    ns = _parse_args()
    overrides = {}
    if ns.engine:
        overrides["engine"] = ns.engine
    if ns.mode:
        overrides["mode"] = ns.mode
    if ns.samples:
        overrides["samples"] = ns.samples
    if ns.camera:
        overrides["camera_type"] = ns.camera

    # Resolve to absolute paths: Blender relativizes render.filepath against its
    # own base (not the process CWD), so a relative --out would land off-repo.
    bundle = os.path.abspath(ns.bundle)
    out_path = os.path.abspath(ns.out)

    # Vector export: build in a line mode and write SVG / PDF instead of a PNG.
    if ns.vector:
        mode = ns.mode or "linework"
        if mode not in _LINE_MODES:
            sys.stderr.write("--vector needs a line mode "
                             "(linework/pen/sketch/cel); got --mode %s\n" % mode)
            sys.exit(2)
        overrides["mode"] = mode
        vec_out = os.path.splitext(out_path)[0] + "." + ns.vector
        from blender.pipeline.run import run_vector_pipeline
        out = run_vector_pipeline(bundle, vec_out, ns.vector,
                                  overrides=overrides or None)
        print("Blendit: vector ->", out)
        if ns.open and os.path.isfile(out):
            try:
                os.startfile(out)
            except Exception:
                pass
        return

    from blender.pipeline.run import run_pipeline
    try:
        out = run_pipeline(bundle, out_path, overrides=overrides or None)
    except Exception:
        # The Revit launcher is DETACHED, so without a visible signal a failed render
        # just silently never opens. Drop a note where the PNG would have been (and
        # open it if asked) so the user isn't left wondering, then re-raise for a
        # non-zero exit + full traceback in the log.
        import traceback
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        note = os.path.join(os.path.dirname(out_path) or ".", "render_FAILED.txt")
        try:
            f = open(note, "w")
            try:
                f.write("Blendit render failed.\n\n" + tb)
            finally:
                f.close()
            if ns.open:
                try:
                    os.startfile(note)
                except Exception:
                    pass
        except Exception:
            pass
        raise
    print("Blendit: rendered ->", out)

    if ns.open and os.path.isfile(out):
        # Blender opens its own result so the Revit launcher can return immediately
        # (no blocking wait). startfile is Windows-only; harmless to guard.
        try:
            os.startfile(out)
        except Exception:
            pass


if __name__ == "__main__":
    main()
