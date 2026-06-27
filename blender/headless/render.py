"""Headless bpy entry point.

    blender --background --python blender/headless/render.py -- \
        --bundle "<scene_spec.json or bundle dir>" --out "<output.png>" \
        [--engine CYCLES|EEVEE] [--mode MODE] [--samples N] [--camera persp|ortho]

MODE is one of: realistic, white, shadow, specular, linework, pen, sketch, cel.

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
                            "pen", "sketch", "cel"])
    p.add_argument("--samples", type=int)
    p.add_argument("--camera", choices=["perspective", "orthographic"],
                   help="override the view's camera type")
    p.add_argument("--open", action="store_true",
                   help="open the rendered PNG when done (so the launcher needn't wait)")
    return p.parse_args(args)


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
