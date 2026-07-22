"""Pipeline step: SceneSpec materials -> Principled BSDF, assigned by element.

Contract 0.1.0 numeric mapping (base_color, metallic, roughness, transparency,
ior, emissive) drives the Principled BSDF. Transparency routes to physical
transmission (glass), not flat alpha.

SURFACE TEXTURE, in precedence order:
  1. an explicit per-material override from the N-panel ("plain" or a library key),
  2. REAL Revit textures - the record's `maps` block (contract 0.2.0: the
     appearance-asset bitmaps bundled under textures/), box-projected at their
     real-world scale on Object coordinates (== world metres; Revit gives no UVs,
     and real-world box mapping is exactly how Revit maps them itself),
  3. the curated `material_library` surface matched on the Revit material *name*,
     tinted by the Revit base colour.

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
# Render View) agrees. {material_id: "auto"|"plain"|"brick"|"wood"|...}.
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


def build_material(rec, engine="CYCLES", surface="auto", base_dir=None):
    """`surface` selects the texture source: "auto" prefers the record's real Revit
    maps (falling back to the name-matched library), "plain" forces flat colour, any
    other value forces that specific library surface (the N-panel override).
    `base_dir` is the bundle dir map uris resolve against."""
    mat = bpy.data.materials.new(rec.get("name") or rec.get("id") or "RevitMaterial")
    # The contract material id, queryable after the by-id build dict is gone -
    # the live-sync applier assigns materials to patched-in objects by this.
    mat["bir_material_id"] = rec.get("id") or ""
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
        # Texture source (precedence in the module docstring): explicit override >
        # real Revit maps > name-matched library > flat colour.
        tint = rec.get("base_color", [0.8, 0.8, 0.8])
        if surface == "plain":
            pass
        elif surface and surface != "auto":
            material_library.build_surface(nt, bsdf, surface, tint, roughness)
        elif not _build_revit_maps(nt, bsdf, rec, base_dir):
            material_library.decorate(nt, bsdf, rec.get("name", ""), tint, roughness)

    emissive = rec.get("emissive")
    if emissive:
        bsdf.inputs["Emission Color"].default_value = _rgba(emissive)
        bsdf.inputs["Emission Strength"].default_value = float(
            rec.get("emissive_strength") or 1.0)
    return mat


def _map_path(entry, base_dir):
    uri = (entry or {}).get("uri")
    if not uri or not base_dir:
        return None
    path = os.path.join(base_dir, uri.replace("/", os.sep))
    return path if os.path.isfile(path) else None


def _build_revit_maps(nt, bsdf, rec, base_dir):
    """Real Revit appearance textures (contract 0.2.0 `maps`): the diffuse bitmap
    box-projected at its real-world scale, plus the bump map when present. Returns
    False when there's no resolvable diffuse map, so the caller can fall back to
    the curated library. Object coords == world metres (merge bakes the matrix),
    so a 0.6 m brick tile is 0.6 m on the wall - the same real-world mapping
    Revit uses, no UVs needed."""
    maps = rec.get("maps") or {}
    diffuse = maps.get("diffuse") or {}
    dpath = _map_path(diffuse, base_dir)
    if dpath is None:
        return False

    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-900, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-700, 0)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    sx, sy = _scale_m(diffuse)
    # Box projection samples the XY/XZ/YZ planes: walls read U from world X or Y
    # and V from Z. 1/sx on both horizontals + 1/sy on Z keeps every wall's tile
    # sx wide and sy tall (floors get sx x sx - square tiles, the common case).
    mp.inputs["Scale"].default_value = (1.0 / sx, 1.0 / sx, 1.0 / sy)
    off = diffuse.get("offset_m") or [0.0, 0.0]
    mp.inputs["Location"].default_value = (float(off[0]), float(off[1]), 0.0)
    rot = float(diffuse.get("rotation_deg") or 0.0)
    if rot:
        import math
        mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(rot))

    img = nt.nodes.new("ShaderNodeTexImage")
    img.location = (-460, 60)
    img.image = bpy.data.images.load(dpath, check_existing=True)
    img.projection = "BOX"
    img.projection_blend = 0.25
    nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
    nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])

    bpath = _map_path(maps.get("bump"), base_dir)
    if bpath is not None:
        bimg = nt.nodes.new("ShaderNodeTexImage")
        bimg.location = (-460, -280)
        bimg.image = bpy.data.images.load(bpath, check_existing=True)
        bimg.image.colorspace_settings.name = "Non-Color"
        bimg.projection = "BOX"
        bimg.projection_blend = 0.25
        nt.links.new(mp.outputs["Vector"], bimg.inputs["Vector"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (-200, -280)
        amount = float((maps.get("bump") or {}).get("amount") or 0.3)
        bump.inputs["Strength"].default_value = max(0.0, min(1.0, amount))
        nt.links.new(bimg.outputs["Color"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return True


def _scale_m(entry):
    scale = entry.get("scale_m") or [0.3, 0.3]
    sx = max(1e-4, float(scale[0]))
    sy = max(1e-4, float(scale[1] if len(scale) > 1 else scale[0]))
    return sx, sy


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
    base_dir = (loaded.spec or {}).get("_override_dir")  # == the bundle dir
    by_id = {rec["id"]: build_material(rec, engine, overrides.get(rec["id"], "auto"),
                                       base_dir=base_dir)
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
