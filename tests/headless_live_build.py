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
live._BUSY = True
# Register the timer exactly as main() does. The build stages LOAD FILES
# (read_factory_settings / open_mainfile), and a file load removes
# non-persistent timers - the assert below is the regression guard for the
# "banner frozen on 'Applying materials...'" bug (persistent=True is required).
bpy.app.timers.register(live._deferred_build, first_interval=1000.0,
                        persistent=True)
steps = 0
while live._deferred_build() is not None:   # drive the staged build to completion
    steps += 1
    assert bpy.app.timers.is_registered(live._deferred_build), (
        "the build timer was wiped by a file load at stage %d - main() must "
        "register _deferred_build with persistent=True" % steps)
assert steps >= 3, "expected multiple build stages, got %d" % steps
try:
    bpy.app.timers.unregister(live._deferred_build)
except Exception:
    pass

assert live._SPEC is not None, "build did not set _SPEC"
assert live._LOADED is not None, "build did not set _LOADED"
assert live._BUSY is False, "busy flag not cleared after build"
n = len([o for o in bpy.data.objects if o.type == "MESH"])
assert n < 200, "merge did not run (%d objects)" % n
assert bpy.context.scene.camera is not None, "no camera after prepare"
print("deferred_build OK: %d mesh objects, mode=%s, capture_dir=%s"
      % (n, live._SPEC.get("render", {}).get("mode"), live._CAPTURE_DIR))
print("LIVE BUILD OK")
