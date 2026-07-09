"""Manual smoke runner: render the fixture in EVERY render mode. Needs Blender.

    blender --background --python tests/smoke_render.py

Renders tiny PNGs to out/smoke_<mode>.png and asserts each is non-trivial. A quick
"did any preset break against this Blender version" check (handy given the API
churn between 4.2 LTS and newer releases). Iterates the canonical RENDER_MODES so a
newly added mode is smoke-tested automatically - a preset that throws while building
its material (e.g. a wrong socket name) is caught here instead of shipping.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bir_contract.scene_spec import RENDER_MODES
MODES = list(RENDER_MODES)
_THRESHOLD = 2000  # bytes; a real render of the box is far bigger


def main():
    from blender.pipeline.run import run_pipeline
    bundle = os.path.join(_ROOT, "tests", "fixtures")
    out_dir = os.path.join(_ROOT, "out")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    failures = []
    for mode in MODES:
        out = os.path.join(out_dir, "smoke_%s.png" % mode)
        try:
            if os.path.isfile(out):
                os.remove(out)          # don't count a stale PNG as a pass
            run_pipeline(bundle, out, overrides={
                "engine": "CYCLES", "mode": mode, "samples": 4,
                "resolution": [240, 135],
            })
            size = os.path.getsize(out) if os.path.isfile(out) else 0
            ok = size >= _THRESHOLD
            detail = "(%d bytes)" % size
        except Exception as ex:         # a preset that throws mid-build (wrong
            ok = False                  # socket name, missing link) fails just its
            detail = "raised %s: %s" % (type(ex).__name__, ex)  # own mode, not the run
        print("  %-12s -> %s %s" % (mode, "OK" if ok else "FAIL", detail))
        if not ok:
            failures.append(mode)

    if failures:
        print("FAILED modes:", failures)
        sys.exit(1)
    print("All %d modes rendered non-trivial PNGs." % len(MODES))


if __name__ == "__main__":
    main()
