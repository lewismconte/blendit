"""Revit appearance assets -> texture maps + PBR hints (contract 0.2.0).

Walks Material.AppearanceAssetId -> AppearanceAssetElement.GetRenderingAsset(),
a Protein Asset tree of AssetProperty nodes. Extracts, when present:

  * the diffuse color / diffuse BITMAP (connected UnifiedBitmap) with its
    real-world scale / offset / rotation,
  * the bump bitmap + amount,
  * glossiness (-> roughness), transparency, and a coarse appearance class
    (metal / wood / concrete / ... from the asset's schema).

Every step is guarded: assets vary WILDLY by schema and library version, and a
material with no readable asset must simply fall back to the graphics shading.
Texture paths land as ABSOLUTE `source_path`s here; the glTF exporter copies the
files into the bundle's `textures/` dir and rewrites them to relative `uri`s.

Revit gives no UVs (see PYREVIT-DEV-GUIDE section 7) - scale/offset/rotation are
enough because Revit's own mapping is real-world box projection, which the
Blender side reproduces with Object-coordinate box mapping.

IronPython 2.7 + pure ASCII. Keep it that way.
"""
import os

from bir_extract import _compat

DB = _compat.DB

_FT_TO_M = 0.3048
_IN_TO_M = 0.0254

# Ordered diffuse-slot candidates across the common Protein schemas. The first
# property that exists wins; a generic scan catches exotic schemas.
_DIFFUSE_NAMES = (
    "generic_diffuse", "ceramic_color", "concrete_color", "masonrycmu_color",
    "metallicpaint_base_color", "hardwood_color", "plasticvinyl_color",
    "stone_color", "wallpaint_color", "metal_color",
    "solidglass_transmittance_custom_color", "glazing_transmittance_map",
    "water_tint_color",
)
_BUMP_NAMES = (
    "generic_bump_map", "concrete_bump_map", "stone_bump_map",
    "masonrycmu_pattern_map", "hardwood_imperfections_shader",
)
_GLOSS_NAMES = ("generic_glossiness", "ceramic_application", "stone_application")
_TRANSPARENCY_NAMES = ("generic_transparency",)

# BaseSchema -> coarse appearance_class (drives e.g. the metallic hint).
_SCHEMA_CLASS = {
    "generic": "generic", "metal": "metal", "metallicpaint": "metal",
    "solidglass": "glass", "glazing": "glass", "mirror": "mirror",
    "ceramic": "ceramic", "stone": "stone", "masonrycmu": "masonry",
    "concrete": "concrete", "hardwood": "wood", "plasticvinyl": "plastic",
    "wallpaint": "wallpaint", "water": "water",
}

# Where Autodesk material-library textures live when the stored path is relative.
_TEXTURE_ROOTS = (
    r"C:\Program Files (x86)\Common Files\Autodesk Shared\Materials\Textures",
    r"C:\Program Files\Common Files\Autodesk Shared\Materials\Textures",
    r"C:\Program Files (x86)\Common Files\Autodesk Shared\Materials\Textures\1\Mats",
    r"C:\Program Files\Common Files\Autodesk Shared\Materials\Textures\1\Mats",
)


def read_appearance(doc, mat):
    """(Document, DB.Material) -> dict of Material-record updates (possibly {}).

    Returns only the keys it could actually read; the caller merges them over
    the graphics-shading record. Never raises."""
    try:
        asset = _rendering_asset(doc, mat)
        if asset is None:
            return {}
        out = {}
        klass = _appearance_class(asset)
        if klass:
            out["appearance_class"] = klass
            if klass == "metal":
                out["metallic"] = 0.85

        diffuse = _find_first(asset, _DIFFUSE_NAMES) or _scan_diffuse(asset)
        if diffuse is not None:
            color = _color_of(diffuse)
            if color is not None:
                out["base_color"] = color
            dmap = _bitmap_of(diffuse)
            if dmap is not None:
                out.setdefault("maps", {})["diffuse"] = dmap

        bump = _find_first(asset, _BUMP_NAMES)
        if bump is not None:
            bmap = _bitmap_of(bump)
            if bmap is not None:
                bmap["amount"] = _bump_amount(asset)
                out.setdefault("maps", {})["bump"] = bmap

        gloss = _double_of(_find_first(asset, _GLOSS_NAMES))
        if gloss is not None and 0.0 <= gloss <= 1.0:
            out["glossiness"] = gloss
            out["roughness"] = max(0.05, min(1.0, 1.0 - gloss))

        transp = _double_of(_find_first(asset, _TRANSPARENCY_NAMES))
        if transp is not None and transp > 0.0:
            out["transparency"] = max(0.0, min(1.0, transp))
        return out
    except Exception:
        return {}


# --- asset access -------------------------------------------------------------
def _rendering_asset(doc, mat):
    try:
        aid = mat.AppearanceAssetId
        if aid is None or aid == DB.ElementId.InvalidElementId:
            return None
        aae = doc.GetElement(aid)
        if aae is None:
            return None
        asset = aae.GetRenderingAsset()
        # Some library materials return an empty (unexpanded) asset - nothing
        # to read; the graphics fallback covers them.
        if asset is None or asset.Size == 0:
            return None
        return asset
    except Exception:
        return None


def _find(asset, name):
    try:
        p = asset.FindByName(name)
        if p is not None:
            return p
    except Exception:
        pass
    try:  # older API: index scan
        for i in range(asset.Size):
            p = asset[i]
            if p is not None and p.Name == name:
                return p
    except Exception:
        pass
    return None


def _find_first(asset, names):
    for n in names:
        p = _find(asset, n)
        if p is not None:
            return p
    return None


def _scan_diffuse(asset):
    """Fallback for schemas not in the candidate list: the first color-array
    property whose name says diffuse/color (skipping tints and glows)."""
    try:
        for i in range(asset.Size):
            p = asset[i]
            if p is None:
                continue
            n = str(p.Name).lower()
            if ("diffuse" in n or n.endswith("_color")) and \
                    "tint" not in n and "glow" not in n:
                if _color_of(p) is not None or _has_connected(p):
                    return p
    except Exception:
        pass
    return None


def _appearance_class(asset):
    try:
        p = _find(asset, "BaseSchema")
        schema = str(p.Value).lower() if p is not None else str(asset.Name).lower()
        for key in _SCHEMA_CLASS:
            if key in schema:
                return _SCHEMA_CLASS[key]
    except Exception:
        pass
    return ""


# --- property readers ---------------------------------------------------------
def _color_of(prop):
    """AssetPropertyDoubleArray4d -> [r, g, b] (protein colors are linear)."""
    try:
        vals = list(prop.GetValueAsDoubles())
        if len(vals) >= 3:
            return [float(vals[0]), float(vals[1]), float(vals[2])]
    except Exception:
        pass
    return None


def _double_of(prop):
    if prop is None:
        return None
    try:
        return float(prop.Value)
    except Exception:
        return None


def _has_connected(prop):
    try:
        return prop.NumberOfConnectedProperties > 0
    except Exception:
        return False


def _bump_amount(asset):
    p = _find(asset, "generic_bump_amount")
    val = _double_of(p)
    if val is None:
        return 0.3
    return max(0.0, min(2.0, abs(val)))


# --- connected UnifiedBitmap --------------------------------------------------
def _bitmap_of(prop):
    """Connected UnifiedBitmap -> {"source_path", "scale_m", "offset_m",
    "rotation_deg"} or None. source_path is absolute; the exporter bundles it."""
    try:
        if not _has_connected(prop):
            return None
        sub = prop.GetSingleConnectedAsset()
        if sub is None:
            return None
        pathp = _find(sub, "unifiedbitmap_Bitmap")
        path = _resolve_texture_path(pathp.Value if pathp is not None else None)
        if not path:
            return None
        return {
            "source_path": path,
            "scale_m": [_distance_m(sub, "texture_RealWorldScaleX", 0.3),
                        _distance_m(sub, "texture_RealWorldScaleY", 0.3)],
            "offset_m": [_distance_m(sub, "texture_RealWorldOffsetX", 0.0),
                         _distance_m(sub, "texture_RealWorldOffsetY", 0.0)],
            "rotation_deg": _double_of(_find(sub, "texture_WAngle")) or 0.0,
        }
    except Exception:
        return None


def _distance_m(asset, name, default):
    """AssetPropertyDistance -> metres. Unit API churned (ForgeTypeId on 2022+,
    DisplayUnitType before); default assumption is inches (the Protein default)."""
    p = _find(asset, name)
    if p is None:
        return default
    try:
        val = float(p.Value)
    except Exception:
        return default
    try:  # modern: ForgeTypeId -> internal feet -> metres
        ft = DB.UnitUtils.ConvertToInternalUnits(val, p.GetUnitTypeId())
        return ft * _FT_TO_M
    except Exception:
        pass
    try:  # legacy enum path
        ft = DB.UnitUtils.ConvertToInternalUnits(val, p.DisplayUnitType)
        return ft * _FT_TO_M
    except Exception:
        pass
    return val * _IN_TO_M


def _resolve_texture_path(raw):
    """Protein stores one or more |-separated paths, often relative to the
    Autodesk shared texture folders. Return the first that exists, else None."""
    if not raw:
        return None
    for piece in str(raw).split("|"):
        piece = piece.strip().replace("/", os.sep)
        if not piece:
            continue
        if os.path.isabs(piece) and os.path.isfile(piece):
            return piece
        for root in _TEXTURE_ROOTS:
            candidate = os.path.join(root, piece)
            if os.path.isfile(candidate):
                return candidate
    return None
