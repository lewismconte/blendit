"""Live-sync applier end-to-end (headless bpy, no Revit).

Run: blender --background --python tests/headless_sync_apply.py

Imports the fixture UN-MERGED (the live-sync session shape), then drives the
REAL applier - update, add, remove - through a REAL spool roundtrip
(write_patch on disk -> consume_spool), asserting WORLD-SPACE geometry so any
axis-swap or scale drift between raw patch meshes (Revit feet, Z-up) and the
glTF-imported session fails loudly, not silently.
"""
import os
import shutil
import sys
import tempfile

import bpy
from mathutils import Vector

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
for p in (_ROOT, os.path.join(_ROOT, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

FT = 0.3048   # scale_to_meters in the fixture


def _world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts),
                 min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts),
                 max(p.z for p in pts)))
    return lo, hi


def _close(a, b, tol=1e-4):
    return abs(a - b) <= tol


def main():
    from blender.pipeline.import_bundle import reset_scene, import_bundle
    from blender.pipeline.materials import apply_materials
    from blender.interactive import sync_apply
    from bir_contract import transport

    # --- an un-merged session (the live-sync shape: one object per element) --
    bundle = os.path.join(_ROOT, "tests", "fixtures")
    reset_scene()
    loaded = import_bundle(bundle)          # NO merge_by_material on purpose
    apply_materials(loaded)                 # materials by spec id
    bpy.context.view_layer.update()

    box = bpy.data.objects.get("Box_1")
    glass = bpy.data.objects.get("Glass_1")
    assert box is not None and glass is not None, \
        "un-merged import must keep per-element objects named by node"
    lo, hi = _world_bbox(box)
    assert _close(hi.x - lo.x, 10 * FT, 1e-3), \
        "box should be 10ft wide in metres, got %.4f" % (hi.x - lo.x)
    print("un-merged import OK (Box_1 spans %.4f m)" % (hi.x - lo.x))

    # --- wire the real applier + a real spool --------------------------------
    tmp = tempfile.mkdtemp(prefix="blendit_sync_test_")
    spool = transport.patch_dir_of(tmp, create=True)
    sync_apply.configure(spec=loaded.spec, spool=spool)

    # --- patch 1: UPDATE Box_1 -> a 10ft cube moved +10ft in X ---------------
    # (a triangle-pair box face is enough to measure world placement)
    verts = [(10.0, 0.0, 0.0), (20.0, 0.0, 0.0), (20.0, 10.0, 0.0),
             (10.0, 10.0, 0.0), (10.0, 0.0, 10.0), (20.0, 0.0, 10.0),
             (20.0, 10.0, 10.0), (10.0, 10.0, 10.0)]
    faces = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7),
             (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6)]
    old_mats = [m.name for m in box.data.materials if m is not None]
    transport.write_patch(spool, 1, [
        {"node": "Box_1", "vertices": [list(v) for v in verts],
         "faces": [list(f) for f in faces], "material_id": "mat_concrete"},
    ], [])

    # --- patch 2: ADD a new node + REMOVE Glass_1 ----------------------------
    transport.write_patch(spool, 2, [
        {"node": "Walls_999",
         "vertices": [[0.0, -20.0, 0.0], [10.0, -20.0, 0.0], [10.0, -20.0, 8.0],
                      [0.0, -20.0, 8.0]],
         "faces": [[0, 1, 2], [0, 2, 3]], "material_id": "mat_concrete"},
    ], ["Glass_1"])

    n = sync_apply.consume_spool()
    assert n == 2, "expected 2 patches applied, got %d" % n
    assert transport.list_patches(spool) == [], "spool must drain"
    print("spool consumed OK (2 patches, drained)")

    # UPDATE: world-space position proves scale kept + no axis swap
    bpy.context.view_layer.update()
    lo, hi = _world_bbox(box)
    assert _close(lo.x, 10 * FT, 1e-3) and _close(hi.x, 20 * FT, 1e-3), \
        "moved box spans x=[%.4f, %.4f] m, want [%.4f, %.4f]" % \
        (lo.x, hi.x, 10 * FT, 20 * FT)
    assert _close(hi.z, 10 * FT, 1e-3), "box height %.4f, want %.4f" % \
        (hi.z, 10 * FT)
    new_mats = [m.name for m in box.data.materials if m is not None]
    assert new_mats == old_mats and new_mats, \
        "update must keep the object's materials (%r -> %r)" % (old_mats, new_mats)
    print("update OK (world pos exact, materials kept: %r)" % new_mats)

    # ADD: exists, world-scaled, node-stamped, material inherited by id
    wall = bpy.data.objects.get("Walls_999")
    assert wall is not None, "added node missing"
    assert wall.get("node") == "Walls_999", "added node not stamped"
    lo, hi = _world_bbox(wall)
    assert _close(hi.x - lo.x, 10 * FT, 1e-3) and _close(hi.z - lo.z, 8 * FT, 1e-3), \
        "added wall spans %.4f x %.4f m" % (hi.x - lo.x, hi.z - lo.z)
    wmats = [m.name for m in wall.data.materials if m is not None]
    assert wmats == old_mats, \
        "add should inherit the concrete material by id (%r != %r)" % \
        (wmats, old_mats)
    print("add OK (scaled, stamped, material by id)")

    # REMOVE: gone
    assert bpy.data.objects.get("Glass_1") is None, "removed node still present"
    print("remove OK")

    # --- update-for-unknown-node degrades to an add --------------------------
    counts = sync_apply.apply_patch({
        "kind": "blendit_patch", "seq": 3,
        "updated": [{"node": "Roofs_777",
                     "vertices": [[0, 0, 12], [10, 0, 12], [10, 10, 12]],
                     "faces": [[0, 1, 2]], "material_id": "mat_concrete"}],
        "removed": ["NoSuchNode_1"]})
    assert counts["added"] == 1 and counts["missing"] == 1, counts
    assert bpy.data.objects.get("Roofs_777") is not None
    print("degradation paths OK (%r)" % counts)

    shutil.rmtree(tmp, ignore_errors=True)
    print("SYNC APPLY OK")


main()
