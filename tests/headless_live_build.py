"""Validate live._deferred_build() end to end on the committed fixture bundle (the
build now runs on a timer, which --background won't fire, so call it directly).

Run: blender --background --python tests/headless_live_build.py
"""
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import blender.interactive.live as live

# Portable: the fixture bundle shipped in the repo (no Revit, no machine-specific
# cache). Exercises the full fresh-import path: import + merge + prepare.
BUNDLE = os.path.join(_HERE, "fixtures")


class _NS(object):
    bundle = BUNDLE
    blend = None            # fresh-import path (exercises import + merge + prepare)
    save_blend = None
    capture_dir = None
    engine = "EEVEE"
    mode = "white"


live._register_ui()
live._BUILD_ARGS = _NS()
live._deferred_build()      # runs the build synchronously here

assert live._SPEC is not None, "build did not set _SPEC"
assert live._LOADED is not None, "build did not set _LOADED"
assert live._BUSY is False, "busy flag not cleared after build"
n = len([o for o in bpy.data.objects if o.type == "MESH"])
assert n < 200, "merge did not run (%d objects)" % n
assert bpy.context.scene.camera is not None, "no camera after prepare"
print("deferred_build OK: %d mesh objects, mode=%s, capture_dir=%s"
      % (n, live._SPEC.get("render", {}).get("mode"), live._CAPTURE_DIR))
print("LIVE BUILD OK")
