"""Manual smoke runner: render the fixture in all five modes. Needs Blender.

    blender --background --python tests/smoke_render.py

Renders tiny PNGs to out/smoke_<mode>.png and asserts each is non-trivial. A quick
"did any preset break against this Blender version" check (handy given the API
churn between 4.2 LTS and newer releases).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

MODES = ["realistic", "white", "shadow", "linework", "specular"]
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
        run_pipeline(bundle, out, overrides={
            "engine": "CYCLES", "mode": mode, "samples": 4,
            "resolution": [240, 135],
        })
        size = os.path.getsize(out) if os.path.isfile(out) else 0
        ok = size >= _THRESHOLD
        print("  %-10s -> %s (%d bytes)" % (mode, "OK" if ok else "FAIL", size))
        if not ok:
            failures.append(mode)

    if failures:
        print("FAILED modes:", failures)
        sys.exit(1)
    print("All %d modes rendered non-trivial PNGs." % len(MODES))


if __name__ == "__main__":
    main()
