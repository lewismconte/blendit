"""Pipeline step: SceneSpec materials -> Principled BSDF, assigned by element.

Contract 0.1.0 numeric mapping (base_color, metallic, roughness, transparency,
ior, emissive) drives the Principled BSDF. Transparency routes to physical
transmission (glass), not flat alpha.

SURFACE TEXTURE comes from `material_library`: opaque materials are matched on the
Revit material *name* to a curated procedural surface (brick / wood / concrete /
...), tinted by the Revit base colour. This is the "curated library" path - it
needs no contract change and no UVs (Revit carries neither textures nor UVs
cleanly; see material_library.py). If the record ever carries an explicit
`base_color_texture` (the future Revit appearance-asset extraction path, contract
0.2.0), that takes precedence over the library.

The richer category-aware mapping from the brief's Appendix D (mirror / water
distinct, Bevel edge highlights) keys off a deferred `appearance_class` field.

The SceneSpec is the source of truth, so this REPLACES whatever materials the
glTF importer created.
"""
import json
import os

import bpy

from . import material_library

# Principled v2 (Blender 4.x) socket names.
_TRANSMISSION = "Transmission Weight"

# Per-material surface overrides chosen in the interactive N-panel persist here, next
# to the bundle, so every path (live re-apply, mode switch, Render Final, headless
# Render Loaded Model) agrees. {material_id: "auto"|"plain"|"brick"|"wood"|...}.
OVERRIDES_FILENAME = "material_overrides.json"


def load_overrides(dirpath):
    if not dirpath:
        return {}
    try:
        with open(os.path.join(dirpath, OVERRIDES_FILENAME)) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_overrides(dirpath, mapping):
    if not dirpath:
        return
    try:
        with open(os.path.join(dirpath, OVERRIDES_FILENAME), "w") as f:
            json.dump(mapping, f, indent=2)
    except Exception:
        pass


def _overrides_for(spec):
    # `_override_dir` is a Blender-side runtime annotation (set by run.import_scene /
    # the live session), NOT a contract field.
    return load_overrides((spec or {}).get("_override_dir"))


def _rgba(rgb, a=1.0):
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(a))


def build_material(rec, engine="CYCLES", surface="auto"):
    """`surface` selects the texture source: "auto" matches the library by the Revit
    material name (the default), "plain" forces flat colour, any other value forces
    that specific library surface (the N-panel override)."""
    mat = bpy.data.materials.new(rec.get("name") or rec.get("id") or "RevitMaterial")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = _rgba(rec.get("base_color", [0.8, 0.8, 0.8]))
    bsdf.inputs["Metallic"].default_value = float(rec.get("metallic", 0.0))
    bsdf.inputs["IOR"].default_value = float(rec.get("ior", 1.45))

    transparency = float(rec.get("transparency", 0.0))
    roughness = max(0.03, min(1.0, float(rec.get("roughness", 0.5))))
    if transparency > 0.0:
        # Glass-like: physical transmission + smooth surface. (No procedural
        # surface texture - glass reads through, not off, the face.)
        bsdf.inputs["Roughness"].default_value = min(roughness, 0.1)
        if _TRANSMISSION in bsdf.inputs:
            bsdf.inputs[_TRANSMISSION].default_value = transparency
        _setup_eevee_glass(mat, engine)
    else:
        bsdf.inputs["Roughness"].default_value = roughness
        # Curated procedural surface, tinted by the Revit base colour. "auto" matches
        # the library by name (falling back to flat colour); an explicit surface key
        # forces that one; "plain" leaves the flat colour. An explicit
        # base_color_texture (future Revit-extraction path) always wins.
        tint = rec.get("base_color", [0.8, 0.8, 0.8])
        if rec.get("base_color_texture") or surface == "plain":
            pass
        elif surface and surface != "auto":
            material_library.build_surface(nt, bsdf, surface, tint, roughness)
        else:
            material_library.decorate(nt, bsdf, rec.get("name", ""), tint, roughness)

    emissive = rec.get("emissive")
    if emissive:
        bsdf.inputs["Emission Color"].default_value = _rgba(emissive)
        bsdf.inputs["Emission Strength"].default_value = float(
            rec.get("emissive_strength") or 1.0)
    return mat


def _setup_eevee_glass(mat, engine):
    if engine != "EEVEE":
        return
    # EEVEE Next needs raytraced refraction per-material (+ raytracing on in the
    # render settings) or glass renders opaque. Attribute names churned across
    # 4.2-4.4, so guard each.
    for attr in ("use_raytrace_refraction", "use_screen_refraction"):
        if hasattr(mat, attr):
            setattr(mat, attr, True)
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"


def apply_materials(loaded, engine="CYCLES"):
    overrides = _overrides_for(loaded.spec)
    by_id = {rec["id"]: build_material(rec, engine, overrides.get(rec["id"], "auto"))
             for rec in loaded.spec.get("materials", [])}
    elems = {e["node"]: e
             for e in loaded.spec.get("geometry", {}).get("elements", [])}
    for node, obj in loaded.node_to_object.items():
        if getattr(obj, "type", None) != "MESH":
            continue
        mid = (elems.get(node) or {}).get("material_id")
        mat = by_id.get(mid)
        if mat is not None:
            obj.data.materials.clear()
            obj.data.materials.append(mat)


# --- override helpers for the white / shadow presets ------------------------
def make_clay_material(name="Clay", value=0.8, roughness=0.6):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (value, value, value, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def override_all(loaded, mat):
    for obj in loaded.node_to_object.values():
        if getattr(obj, "type", None) == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(mat)
