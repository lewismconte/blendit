"""Validate the live-sync --watch session build end to end (headless).

Run: blender --background --python tests/headless_watch_build.py

Drives live._deferred_build with watch=True on the fixture bundle (timers do
not fire under --background, so the generator is driven directly - the
headless_live_build pattern) and asserts the watch-mode contract:
UN-merged per-element objects, node ids stamped, spool created + stale
patches cleared, the poll timer armed - then lands a REAL patch through the
armed poll callback to prove the loop is closed.
"""
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
for p in (_ROOT, os.path.join(_ROOT, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

import blender.interactive.live as live  # noqa: E402
from blender.interactive import sync_apply  # noqa: E402
from bir_contract import transport  # noqa: E402

BUNDLE = os.path.join(_HERE, "fixtures")


class _NS(object):
    bundle = BUNDLE
    blend = None
    save_blend = None
    capture_dir = None
    engine = "EEVEE"
    mode = "white"
    watch = True


def main():
    # A stale patch spooled BEFORE the session must be cleared by the build.
    spool = transport.patch_dir_of(BUNDLE, create=True)
    transport.write_patch(spool, 999, [], ["StaleNode_1"])

    live._register_ui()
    live._BUILD_ARGS = _NS()
    live._BUSY = True
    while live._deferred_build() is not None:
        pass

    assert live._SPEC is not None and live._LOADED is not None
    # UN-merged: the per-element fixture objects survive under their node names
    box = bpy.data.objects.get("Box_1")
    glass = bpy.data.objects.get("Glass_1")
    assert box is not None and glass is not None, \
        "watch build must keep per-element objects (merge must be skipped)"
    assert not any(o.name.startswith("BIR_Mat_") for o in bpy.data.objects), \
        "merged objects present - watch build merged anyway"
    assert box.get("node") == "Box_1", "node id not stamped on import"
    print("un-merged watch build OK (nodes stamped)")

    # The stale patch is gone; the poll timer is armed.
    assert transport.list_patches(spool) == [], "stale patches not cleared"
    assert bpy.app.timers.is_registered(sync_apply.poll), \
        "sync watcher timer not registered"
    print("spool cleared + watcher armed OK")

    # Close the loop: land a real patch through the armed callback.
    transport.write_patch(spool, 1, [
        {"node": "Walls_500",
         "vertices": [[0.0, 30.0, 0.0], [10.0, 30.0, 0.0], [10.0, 30.0, 8.0]],
         "faces": [[0, 1, 2]], "material_id": "mat_concrete"},
    ], ["Glass_1"])
    interval = sync_apply.poll()
    assert interval == sync_apply.POLL_INTERVAL
    assert bpy.data.objects.get("Walls_500") is not None, "patched add missing"
    assert bpy.data.objects.get("Glass_1") is None, "patched remove missing"
    assert transport.list_patches(spool) == [], "patch not consumed"
    print("patch landed through the armed poll OK")

    try:
        bpy.app.timers.unregister(sync_apply.poll)
    except Exception:
        pass
    transport.clear_patches(spool)
    try:
        os.rmdir(spool)   # leave the committed fixture dir exactly as it was
    except Exception:
        pass
    print("WATCH BUILD OK")


main()
