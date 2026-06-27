"""glTF transport - Blender side."""
import os

import bpy

from contract.transport import (
    Importer, LoadedScene, read_scene_spec, bundle_dir_of,
    check_contract_version, register_importer,
)


class GltfImporter(Importer):
    name = "gltf"

    def can_load(self, bundle_ref):
        spec = read_scene_spec(bundle_ref)
        return spec.get("geometry", {}).get("transport") == "gltf"

    def load(self, bundle_ref):
        spec = read_scene_spec(bundle_ref)
        check_contract_version(spec)
        payload = os.path.join(bundle_dir_of(bundle_ref), spec["geometry"]["uri"])
        before = set(bpy.data.objects)
        # AXIS GOTCHA: glTF is Y-up; Revit and Blender are Z-up. Convert in EXACTLY
        # ONE place. Recommended: write the glTF in glTF-native Y-up on the Revit
        # side, and let Blender's importer convert back to Z-up (its default).
        # If instead you keep Z-up coords in the glTF, disable the importer's
        # conversion so the model isn't rotated 90 degrees.
        bpy.ops.import_scene.gltf(filepath=payload)
        new_objs = [o for o in bpy.data.objects if o not in before]
        # SCALE: apply units.scale_to_meters ONCE to the whole import (geometry +
        # camera + sun distance are handled together by the pipeline, not here, to
        # avoid double-scaling). The importer just gets geometry in.
        node_to_object = {o.name: o for o in new_objs}  # refine to match Element.node
        return LoadedScene(spec, node_to_object=node_to_object)


register_importer(GltfImporter())
