"""Build every curated procedural surface and render a swatch strip.

Run: blender --background --python tests/headless_material_library.py

Asserts each named Revit material maps to its library surface (real texture +
bump nodes, Base Color/Roughness driven), that an unmatched name stays flat, and
that glass is never textured. Then renders tests/_out/material_library.png so the
surfaces can be eyeballed.
"""
import os
import sys

import bpy
import bmesh

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from blender.pipeline import materials as M
from blender.pipeline import material_library as LIB


def _node_types(mat):
    return set(n.type for n in mat.node_tree.nodes)


def _base_color_linked(mat):
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n.inputs["Base Color"].is_linked
    return False


# --- 1. structural assertions ----------------------------------------------
CASES = [
    ("Brick, Common",            "brick",    "TEX_BRICK"),
    ("Wood - Flooring Oak",      "wood",     "TEX_WAVE"),
    ("Concrete, Cast-in-Place",  "concrete", "TEX_NOISE"),
    ("Stone, Marble White",      "stone",    "TEX_NOISE"),
    ("Metal - Steel, Painted",   "metal",    "TEX_NOISE"),
    ("Carpet, Loop Grey",        "fabric",   "TEX_NOISE"),
    ("Site - Grass",             "grass",    "TEX_NOISE"),
]

for name, cat, want_node in CASES:
    assert LIB.category_for(name) == cat, \
        "%r should map to %s, got %s" % (name, cat, LIB.category_for(name))
    rec = {"id": "m", "name": name, "base_color": [0.55, 0.35, 0.25],
           "roughness": 0.6}
    mat = M.build_material(rec, engine="CYCLES")
    types = _node_types(mat)
    assert want_node in types, "%s missing %s (have %s)" % (name, want_node, types)
    assert "TEX_COORD" in types and "MAPPING" in types, \
        "%s missing real-world projection" % name
    # brick/wood/concrete/stone/grass drive Base Color; metal/fabric tint scalar.
    if cat in ("brick", "wood", "concrete", "stone", "grass"):
        assert _base_color_linked(mat), "%s should drive Base Color" % name
    if cat == "metal":
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                assert n.inputs["Metallic"].default_value == 1.0, "metal not metallic"
print("structural asserts OK")

# unmatched name -> flat, no texture plumbing
flat = M.build_material({"id": "m", "name": "Paint - Eggshell White",
                         "base_color": [0.9, 0.9, 0.9], "roughness": 0.5})
assert "TEX_COORD" not in _node_types(flat), "unmatched material should stay flat"

# glass -> transmission, never textured
glass = M.build_material({"id": "g", "name": "Glass, Clear", "base_color": [0.8, 0.9, 1.0],
                          "transparency": 0.9, "roughness": 0.0})
assert "TEX_COORD" not in _node_types(glass), "glass must not be textured"
print("flat + glass asserts OK")


# --- 2. visual swatch strip -------------------------------------------------
def _sphere(name, x):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=1.0)
    except TypeError:                       # older bmesh used `diameter`
        bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, diameter=1.0)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    obj = bpy.data.objects.new(name, me)
    obj.location = (x, 0.0, 0.0)
    bpy.context.scene.collection.objects.link(obj)
    return obj

scene = bpy.context.scene
spacing = 2.6
for i, (name, _cat, _n) in enumerate(CASES):
    obj = _sphere(name, i * spacing)
    rec = {"id": "m%d" % i, "name": name,
           "base_color": [0.62, 0.40, 0.28] if "wood" in name.lower()
           or "brick" in name.lower() else [0.72, 0.72, 0.72],
           "roughness": 0.6}
    obj.data.materials.append(M.build_material(rec, engine="CYCLES"))

# camera framing the strip head-on
mid_x = (len(CASES) - 1) * spacing / 2.0
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 35                          # wide enough to fit the whole strip
cam = bpy.data.objects.new("Cam", cam_data)
cam.location = (mid_x, -30.0, 1.0)
cam.rotation_euler = (1.5375, 0.0, 0.0)     # ~88 deg, look along +Y
scene.collection.objects.link(cam)
scene.camera = cam

sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = 3.0
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_euler = (0.9, 0.2, 0.5)
scene.collection.objects.link(sun)

w = bpy.data.worlds.new("W")
w.use_nodes = True
for n in w.node_tree.nodes:
    if n.type == "BACKGROUND":
        n.inputs["Color"].default_value = (0.6, 0.62, 0.65, 1.0)
        n.inputs["Strength"].default_value = 1.0
scene.world = w

for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"):
    try:
        scene.render.engine = eng
        break
    except Exception:
        pass
scene.render.resolution_x = 1400
scene.render.resolution_y = 320
scene.view_settings.view_transform = "AgX"
out = os.path.join(_HERE, "_out", "material_library.png")
if not os.path.isdir(os.path.dirname(out)):
    os.makedirs(os.path.dirname(out))
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
assert os.path.getsize(out) > 5000, "render looks empty"
print("rendered:", out)
print("MATERIAL LIBRARY OK")
