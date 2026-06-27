"""Per-material surface override: the sidecar forces a surface through apply_materials
even when the Revit name matches nothing (the N-panel Materials list path).

Run: blender --background --python tests/headless_material_override.py
"""
import os
import sys
import tempfile

import bpy
import bmesh

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from blender.pipeline import materials as M


def _cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _types(obj):
    return set(n.type for n in obj.data.materials[0].node_tree.nodes)


# sidecar round-trip
d = tempfile.mkdtemp()
M.save_overrides(d, {"mat_1": "brick"})
assert M.load_overrides(d) == {"mat_1": "brick"}, "sidecar round-trip failed"

# a material whose NAME matches nothing in the library -> would be flat under "auto"
obj = _cube("n0")


class _Loaded(object):
    pass


loaded = _Loaded()
loaded.node_to_object = {"n0": obj}
loaded.spec = {
    "_override_dir": d,
    "materials": [{"id": "mat_1", "name": "Wall Type B",
                   "base_color": [0.6, 0.3, 0.2], "roughness": 0.6}],
    "geometry": {"elements": [{"node": "n0", "material_id": "mat_1"}]},
}

# with the override -> forced brick despite the unmatched name
M.apply_materials(loaded, engine="EEVEE")
assert "TEX_BRICK" in _types(obj), \
    "override should force brick even though 'Wall Type B' matches no keyword"
print("forced-override OK")

# clear the sidecar -> 'auto' on an unmatched name falls back to flat colour
M.save_overrides(d, {})
obj.data.materials.clear()
M.apply_materials(loaded, engine="EEVEE")
assert "TEX_COORD" not in _types(obj), "auto on an unmatched name should be flat"
print("auto-fallback OK")

print("OVERRIDE OK")
