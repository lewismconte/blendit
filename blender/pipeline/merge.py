"""Merge imported meshes by material to cut object count.

Grease Pencil Line Art cost is dominated by OBJECT COUNT, not triangle count: on
the 5121-element test tower, merging cut Line Art build 116s -> 23s and render
348s -> 25s (480x270), with no loss of line quality. So after import we combine all
meshes that share a material into one object each (~one per material).

WHY BMESH, NOT bpy.ops.object.join(): the join operator needs a full window/area
context and SILENTLY FAILS in the live session's startup-timer context - it renamed
one object per group but left the rest behind (a .blend with 36 merged objects +
~3900 stray real-material objects -> "white mode" showed real materials). bmesh is
pure data API, so it works in any context and we delete the originals ourselves.

The look is unchanged because the presets assign exactly one material per object,
keyed by material id. Each merged object is named BIR_Mat_<material_id> so the id is
recoverable from the name (the .blend cache reopen path uses that).

TRADEOFF: this collapses per-element identity (node_to_object goes from one entry
per Revit element to one per material) - the Phase-4 "data back to Revit" direction,
which would return as a face-attribute pass.
"""
import bpy
import bmesh

MERGED_PREFIX = "BIR_Mat_"
_DEFAULT_MAT = "mat_default"


def material_id_from_name(name):
    """-> the material id encoded in a merged object's name, or None."""
    if name and name.startswith(MERGED_PREFIX):
        return name[len(MERGED_PREFIX):]
    return None


def merge_by_material(loaded):
    """Combine imported meshes into one object per material. Mutates `loaded`
    (node_to_object + spec.geometry.elements) and returns it."""
    spec = loaded.spec
    elems = {e["node"]: e for e in spec.get("geometry", {}).get("elements", [])}

    groups = {}    # material_id -> [objects]
    cats = {}      # material_id -> a representative category
    for node, obj in loaded.node_to_object.items():
        if getattr(obj, "type", None) != "MESH":
            continue
        rec = elems.get(node) or {}
        mid = rec.get("material_id") or _DEFAULT_MAT
        groups.setdefault(mid, []).append(obj)
        cats.setdefault(mid, rec.get("category", ""))

    new_node_to_object = {}
    new_elements = []
    for mid, obj_list in groups.items():
        merged = _merge_group(obj_list, mid)
        if merged is None:
            continue
        new_node_to_object[merged.name] = merged
        new_elements.append({"node": merged.name, "material_id": mid,
                             "category": cats.get(mid, "")})

    if new_node_to_object:                 # never wipe the scene on a merge failure
        loaded.node_to_object = new_node_to_object
        spec.setdefault("geometry", {})["elements"] = new_elements
    try:
        # obj.bound_box is lazy; _bake_transform mutates meshes in place, and the
        # camera framing reads bound_box right after - refresh or it frames the
        # stale pre-bake bounds.
        bpy.context.view_layer.update()
    except Exception:
        pass
    return loaded


def _bake_transform(obj):
    """Bake the object's world transform into its vertices (identity transform
    after). The multi-object path below gets this for free via tmp.transform();
    the single-object rename shortcut MUST do it too, or its Object texture
    coordinates stay in Revit feet while every other merged object's are world
    metres - real-world-scale textures (library + Revit maps) would tile 3.28x
    too small on exactly the materials that appear on one element."""
    try:
        import mathutils
        if obj.matrix_world == mathutils.Matrix.Identity(4):
            return
        if obj.data.users > 1:              # never mutate a shared mesh
            obj.data = obj.data.copy()
        obj.data.transform(obj.matrix_world)
        obj.matrix_world = mathutils.Matrix.Identity(4)
    except Exception:
        pass


def _merge_group(obj_list, mid):
    """Combine all objects sharing a material into one new object (via bmesh, so it
    is context-independent), then delete the originals."""
    obj_list = [o for o in obj_list
                if o is not None and getattr(o, "type", None) == "MESH"]
    if not obj_list:
        return None
    name = MERGED_PREFIX + str(mid)

    if len(obj_list) == 1:                  # nothing to combine; rename in place
        o = obj_list[0]
        o.name = name
        _bake_transform(o)                  # keep the Object==metres invariant
        return o

    src_mat = None
    for o in obj_list:
        if o.data.materials:
            src_mat = o.data.materials[0]
            break

    bm = bmesh.new()
    for o in obj_list:
        tmp = o.data.copy()
        tmp.transform(o.matrix_world)       # bake world transform (incl. inherited scale)
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    for f in bm.faces:
        f.material_index = 0                # single slot (presets override anyway)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()

    new_obj = bpy.data.objects.new(name, me)
    if src_mat is not None:
        new_obj.data.materials.append(src_mat)
    bpy.context.scene.collection.objects.link(new_obj)

    # Delete the originals - the bug the operator-join left behind in the live
    # session: stray real-material objects the presets never touched.
    for o in obj_list:
        try:
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        except Exception:
            pass
    return new_obj
