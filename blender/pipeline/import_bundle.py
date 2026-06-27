"""Pipeline step 1-2: clean scene + import the bundle via the selected transport.

Transport-agnostic: it picks the importer by `geometry.transport` and applies
`units.scale_to_meters` ONCE to the whole scene. Camera and sun are placed in
source units by their own steps, which apply the same scale to positions /
distances — so nothing is double-scaled.
"""
import bpy

from contract.transport import get_importer, has_importer, read_scene_spec

# Importing this registers the glTF importer as a side effect. New transports
# (e.g. USD) register the same way - the pipeline picks one by geometry.transport.
import blender.transports.gltf.importer  # noqa: F401


def reset_scene():
    """Start from an empty factory scene (also the bpy 'cannot reload' workaround)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_bundle(bundle_ref):
    spec = read_scene_spec(bundle_ref)
    transport = spec.get("geometry", {}).get("transport", "gltf")
    if not has_importer(transport):
        raise ValueError("no importer registered for transport: %s" % transport)
    loaded = get_importer(transport).load(bundle_ref)
    _apply_scale(loaded)
    return loaded


def _apply_scale(loaded):
    scale = float(loaded.spec.get("units", {}).get("scale_to_meters", 1.0))
    if abs(scale - 1.0) < 1e-9:
        return
    # Scale the import roots; children inherit. Camera/world steps scale their own
    # source-unit values by the same factor. We leave the scale on the transform
    # (no transform_apply) — visually identical for rendering and avoids headless
    # context pitfalls. Bevel-radius-in-meters refinements are a Phase 1 concern.
    objs = list(loaded.node_to_object.values())
    roots = [o for o in objs if o.parent is None or o.parent not in objs]
    for o in roots:
        o.scale = (o.scale[0] * scale, o.scale[1] * scale, o.scale[2] * scale)
    # Flush the new transforms through the dependency graph NOW. Otherwise
    # matrix_world stays stale (pre-scale) until the next depsgraph eval, and the
    # camera framing step would compute the bbox in feet while the render uses
    # metres -> camera aimed at empty space.
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
