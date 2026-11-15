"""Prepared-scene .blend cache for the live session.

The slow part of opening a detailed model is the glTF *import* (~100 s on 14k
elements) - even after the extraction is cached, every launch re-imports.
So we cache the imported scene as a .blend: import once, save it, and on the next
launch open the .blend directly (a few seconds) instead of re-importing.

WHAT GETS CACHED: the clean imported geometry only (scaled to metres), BEFORE any
preset has run. The presets rebuild materials/world/look from the SceneSpec, so on
reload we re-run prepare_scene() against the same spec and the scene comes back
identical - and the user can still switch modes live. The sidecar scene_spec.json
stays next to the .blend and is the source of truth on reload.
"""
import os

import bpy

from bir_contract.transport import read_scene_spec, LoadedScene


def save_clean_blend(path):
    """Save the current (freshly imported, pre-preset) scene as the cache.
    copy=True writes the cache WITHOUT repointing the running session at it, so
    the live session keeps working in memory."""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True, copy=True)


def open_blend(path):
    """Open the cached .blend in place of importing. load_ui=False keeps a
    predictable default workspace; the live session arranges Fly mode itself."""
    bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)


def loaded_from_blend(bundle_ref):
    """Rebuild (loaded, spec) from an already-open cached .blend: the geometry is
    in bpy.data, the spec comes from the sidecar. Returns the same (loaded, spec)
    shape as run.import_scene so callers handle both paths identically.

    The cached scene is merged-by-material, but the on-disk sidecar still lists the
    original per-element geometry - so we rebuild geometry.elements from the merged
    objects (obj["material_id"], with the old BIR_Mat_<id> name as fallback), which
    is all the presets need to assign materials. (Falls back to raw object names for
    a non-merged cache.)"""
    from .merge import MERGED_PREFIX, material_id_from_object
    spec = read_scene_spec(bundle_ref)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    merged = [o for o in meshes if o.name.startswith(MERGED_PREFIX)]
    if merged:
        known = {str(rec.get("id")): rec for rec in spec.get("materials", []) or []
                 if rec.get("id")}
        by_name = {}
        for rec in known.values():
            name = rec.get("name")
            if name:
                by_name[str(name)] = str(rec["id"])
        node_to_object = {o.name: o for o in merged}
        elements = []
        for o in merged:
            mid = material_id_from_object(o)
            # Old caches encode the id in the name. New caches use a readable
            # material name + a property; if the property is missing, map the
            # name back through the sidecar.
            if mid not in known:
                mid = by_name.get(mid, mid)
            elements.append({"node": o.name, "material_id": mid})
        spec.setdefault("geometry", {})["elements"] = elements
    else:
        node_to_object = {o.name: o for o in meshes}
    return LoadedScene(spec, node_to_object=node_to_object), spec
