"""Saved Views (camera bookmarks) + batch render + contact sheet, end to end.

Drives the real machinery on the committed fixture bundle: add/rename/persist/
reload/recall/remove bookmarks, batch-render two views (one with a per-view PEN
mode, exercising the Line Art re-trace), and stitch a contact sheet.

Run: blender --background --python tests/headless_views_batch.py
"""
import json
import os
import shutil
import sys
import tempfile

import bpy
import mathutils

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import blender.interactive.live as live  # noqa: E402

BUNDLE = os.path.join(_HERE, "fixtures")
OUT = tempfile.mkdtemp(prefix="blendit_views_")


class _NS(object):
    bundle = BUNDLE
    blend = None
    save_blend = None
    capture_dir = OUT
    engine = "EEVEE"
    mode = "white"


def _drive(gen):
    for _label in gen:
        print("  stage:", _label)


try:
    # --- build the session (the real staged chain) ---------------------------
    live._register_ui()
    live._BUILD_ARGS = _NS()
    live._BUSY = True
    bpy.app.timers.register(live._deferred_build, first_interval=1000.0,
                            persistent=True)
    while live._deferred_build() is not None:
        pass
    st = bpy.context.scene.bir
    st.final_samples = 16
    cam = bpy.context.scene.camera
    assert cam is not None

    # --- add two bookmarks (second from a moved camera) ----------------------
    bpy.ops.bir.bookmark_add()
    cam.location.x += 5.0
    cam.location.z += 2.0
    bpy.context.view_layer.update()
    bpy.ops.bir.bookmark_add()
    assert len(st.bookmarks) == 2, len(st.bookmarks)

    # rename persists via the update callback; give view 2 a per-view mode
    st.bookmarks[0].label = "North Approach"
    st.bookmarks[1].mode = "pen"
    for bm in st.bookmarks:                # tiny frames so the batch is fast
        bm.res_x, bm.res_y = 160, 90
    live._save_bookmarks()

    sidecar = os.path.join(BUNDLE, "bookmarks.json")
    assert os.path.isfile(sidecar), "sidecar not written"
    with open(sidecar) as f:
        data = json.load(f)["bookmarks"]
    assert len(data) == 2 and data[0]["label"] == "North Approach", data
    assert data[1]["mode"] == "pen", data

    # --- reload round-trip ----------------------------------------------------
    st.bookmarks.clear()
    live._load_bookmarks()
    assert len(st.bookmarks) == 2, "reload lost bookmarks"
    assert st.bookmarks[0].label == "North Approach"
    assert st.bookmarks[1].mode == "pen"

    # --- recall restores the exact camera ------------------------------------
    saved = mathutils.Matrix((st.bookmarks[0].matrix[0:4],
                              st.bookmarks[0].matrix[4:8],
                              st.bookmarks[0].matrix[8:12],
                              st.bookmarks[0].matrix[12:16]))
    cam.location = (99.0, 99.0, 99.0)
    bpy.context.view_layer.update()
    st.bookmark_index = 0
    bpy.ops.bir.bookmark_recall()
    bpy.context.view_layer.update()
    diff = max(abs(a - b) for ra, rb in zip(cam.matrix_world, saved)
               for a, b in zip(ra, rb))
    assert diff < 1e-4, "recall did not restore the camera (diff=%s)" % diff
    print("bookmarks: add/rename/persist/reload/recall OK")

    # --- batch render: 2 views, one PEN (line re-trace path) -----------------
    _drive(live._batch_steps())
    finals = os.path.join(OUT, "finals")
    pngs = [f for f in os.listdir(finals) if f.lower().endswith(".png")]
    assert len(pngs) == 2, "expected 2 finals, got %s" % pngs
    assert any(f.startswith("North_Approach") for f in pngs), pngs
    for f in pngs:
        assert os.path.getsize(os.path.join(finals, f)) > 1000, "trivial PNG"
    # the user's mode came back after the pen view
    assert live._current_mode() == "white", live._current_mode()
    print("batch render OK:", sorted(pngs))

    # --- contact sheet (small cells for speed) --------------------------------
    live._SHEET_CELL_LONG = 120
    _drive(live._contact_steps())
    sheets_dir = os.path.join(OUT, "sheets")
    sheets = [f for f in os.listdir(sheets_dir) if f.lower().endswith(".png")]
    assert len(sheets) == 1, sheets
    sheet = bpy.data.images.load(os.path.join(sheets_dir, sheets[0]))
    w, h = sheet.size
    # 9 modes in 3 cols -> 3 rows of ~120px-wide cells + gutters
    assert w > 3 * 120 and h > 3 * 60, "sheet too small: %sx%s" % (w, h)
    assert live._current_mode() == "white", "mode not restored after sheet"
    print("contact sheet OK: %s (%dx%d)" % (sheets[0], w, h))

    # --- remove ----------------------------------------------------------------
    st.bookmark_index = 0
    bpy.ops.bir.bookmark_remove()
    assert len(st.bookmarks) == 1
    with open(sidecar) as f:
        assert len(json.load(f)["bookmarks"]) == 1
    print("remove OK")

    print("VIEWS BATCH OK")
finally:
    # never leave runtime sidecars / renders in the repo fixture dir
    try:
        os.remove(os.path.join(BUNDLE, "bookmarks.json"))
    except Exception:
        pass
    shutil.rmtree(OUT, ignore_errors=True)
