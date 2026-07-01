"""Headless end-to-end check for the .glb transport + .blend scene cache.

Run under Blender:
    blender --background --python tests/headless_glb_cache.py

Steps:
  1. Build a .glb bundle through the REAL Revit-side exporter (a box).
  2. import_bundle() it in Blender (proves .glb imports here).
  3. save_clean_blend() -> open_blend() -> loaded_from_blend() (proves the cache
     round-trips and the geometry survives a save/reopen).
Prints "ALL OK" on success; raises on any failure (non-zero exit for CI).
"""
import os
import sys
import tempfile

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_REVIT_LIB = os.path.join(_ROOT, "lib")
for p in (_ROOT, _REVIT_LIB):
    if p not in sys.path:
        sys.path.insert(0, p)

from bir_contract.transport import MeshData, get_exporter
import bir_transports.gltf.exporter  # noqa: F401  registers the exporter


def _box(node, mid):
    v = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
         (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    f = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
         (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
         (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]
    return MeshData(node, v, f, material_id=mid)


def main():
    out_dir = tempfile.mkdtemp(prefix="bir_e2e_")
    spec = {"contract_version": "0.1.0",
            "units": {"scale_to_meters": 0.3048},
            "materials": [{"id": "mat_1", "name": "Concrete",
                           "base_color": [0.55, 0.55, 0.53]},
                          {"id": "mat_2", "name": "Steel",
                           "base_color": [0.21, 0.21, 0.22]}],
            "geometry": {"elements": [
                {"node": "Wall_1", "element_id": "1", "category": "Walls",
                 "material_id": "mat_1"},
                {"node": "Wall_2", "element_id": "2", "category": "Walls",
                 "material_id": "mat_2"}]}}
    bundle_ref = get_exporter("gltf").export(
        spec, [_box("Wall_1", "mat_1"), _box("Wall_2", "mat_2")], out_dir)
    assert os.path.isfile(os.path.join(out_dir, "scene.glb")), "no scene.glb written"
    print("OK  wrote .glb bundle:", bundle_ref)

    # 2. import the .glb through the pipeline (which merges by material: two
    #    distinct-material boxes -> two BIR_Mat_* objects).
    from blender.pipeline.run import import_scene
    _MERGED = {"BIR_Mat_mat_1", "BIR_Mat_mat_2"}
    loaded, spec2 = import_scene(bundle_ref, overrides={"camera_type": "perspective"})
    names = set(loaded.node_to_object)
    assert names == _MERGED, "merge gave unexpected objects: %s" % names
    print("OK  imported + merged .glb -> objects:", sorted(names))

    # 3. cache round-trip: save clean .blend, reopen, rebuild loaded
    from blender.pipeline import cache as bir_cache
    blend_path = os.path.join(out_dir, "scene.blend")
    bir_cache.save_clean_blend(blend_path)
    assert os.path.isfile(blend_path), "save_clean_blend wrote nothing"
    print("OK  cached .blend:", blend_path, "(%d bytes)" % os.path.getsize(blend_path))

    bir_cache.open_blend(blend_path)
    reloaded, _spec3 = bir_cache.loaded_from_blend(bundle_ref)
    rnames = set(reloaded.node_to_object)
    assert rnames == _MERGED, "reopened .blend wrong objects: %s" % rnames
    print("OK  reopened .blend -> objects:", sorted(rnames))

    # 4. prepare_scene must run on the reopened cache (presets rebuild from spec)
    from blender.pipeline.run import prepare_scene
    prepare_scene(reloaded, spec2)
    assert bpy.context.scene.camera is not None, "prepare_scene set no camera"
    print("OK  prepare_scene on reopened cache (camera + materials applied)")

    print("ALL OK")


main()
