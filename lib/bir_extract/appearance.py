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

Revit's tessellated geometry on our extraction paths carries no UVs; scale /
offset / rotation are enough because Revit's own mapping is real-world box
projection, which the Blender side reproduces with Object-coordinate box mapping.
(The CustomExporter route can expose render UVs via PolymeshTopology.GetUVs();
carrying those is a future fidelity step, not a contract change.)

IronPython 2.7 + pure ASCII. Keep it that way.
"""
import os

from bir_extract import _compat

DB = _compat.DB

_FT_TO_M = 0.3048
_IN_TO_M = 0.0254

# Ordered colour-slot candidates across the common Protein schemas. The first
# property that exists wins; a generic scan catches exotic schemas.
# The Advanced / Physical (Prism) family uses opaque_albedo / metal_f0 /
# layered_diffuse, which the older Generic-only list missed entirely - those
# materials came through with no colour and no texture at all.
_DIFFUSE_NAMES = (
    "generic_diffuse", "opaque_albedo", "metal_f0", "layered_diffuse",
    "transparent_color",
    "ceramic_color", "concrete_color", "masonrycmu_color",
    "metallicpaint_base_color", "hardwood_color", "plasticvinyl_color",
    "stone_color", "wallpaint_color", "metal_color",
    "solidglass_transmittance_custom_color", "glazing_transmittance_map",
    "mirror_tintcolor", "water_tint_color",
)
_BUMP_NAMES = (
    "generic_bump_map", "concrete_bump_map", "stone_bump_map",
    "masonrycmu_pattern_map", "hardwood_imperfections_shader",
)
_GLOSS_NAMES = ("generic_glossiness",)
_ROUGHNESS_NAMES = ("surface_roughness", "layered_roughness", "opaque_roughness")
_TRANSPARENCY_NAMES = ("generic_transparency",)

# BaseSchema -> coarse appearance_class (drives e.g. the metallic hint).
# A TUPLE, not a dict: Python 2.7 / IronPython does not preserve dict order, and
# "metallicpaint" must be tested before "metal" or a metallic paint becomes a
# plain metal. Specific keys come first.
_SCHEMA_CLASS = (
    ("prismmetal", "metal"), ("prismtransparent", "glass"), ("prism", "generic"),
    ("metallicpaint", "metal"), ("solidglass", "glass"), ("glazing", "glass"),
    ("transparent", "glass"), ("mirror", "mirror"),
    ("ceramic", "ceramic"), ("stone", "stone"), ("masonry", "masonry"),
    ("concrete", "concrete"), ("hardwood", "wood"), ("wood", "wood"),
    ("plasticvinyl", "plastic"), ("wallpaint", "wallpaint"), ("water", "water"),
    ("metal", "metal"), ("generic", "generic"), ("advanced", "generic"),
    ("layered", "generic"),
)

# Where Autodesk material-library textures live when the stored path is relative.
# These are fallbacks; _texture_roots() probes the real Common Files folders
# (and Revit.ini's additional render appearance paths) at run time.
_TEXTURE_ROOTS = (
    r"C:\Program Files (x86)\Common Files\Autodesk Shared\Materials\Textures",
    r"C:\Program Files\Common Files\Autodesk Shared\Materials\Textures",
    r"C:\Program Files (x86)\Common Files\Autodesk Shared\Materials\Textures\1\Mats",
    r"C:\Program Files\Common Files\Autodesk Shared\Materials\Textures\1\Mats",
)

_ROOTS_CACHE = {"roots": None}
_EXTRA_CACHE = {}
_PATH_CACHE = {}
_STATS = {"materials": 0, "textured": 0, "missing": 0, "procedural": 0,
          "fallback": 0, "empty": 0, "unreadable": 0}


def read_appearance(doc, mat, shading_color=None):
    """(Document, DB.Material, optional shading RGB) -> Material-record updates.

    Returns only the keys it could actually read; the caller merges them over
    the graphics-shading record. Never raises.

    `shading_color` is the material's graphics colour. When the appearance
    points at a bitmap that is missing or procedural, the asset's render colour
    is usually a white placeholder; keep the shading colour instead (BimGo's
    reconciliation lesson) or the surface renders white instead of its real
    colour."""
    _STATS["materials"] += 1
    try:
        asset = _rendering_asset(doc, mat)
        if asset is None:
            _STATS["empty"] += 1
            return {}
        out = {}
        klass = _appearance_class(asset)
        if klass:
            out["appearance_class"] = klass
            if klass == "metal":
                out["metallic"] = 0.85
            elif klass == "mirror":
                out["metallic"] = 1.0
                out["roughness"] = 0.05
        # Generic schema metal flag (e.g. Metal Stud Layer / Steel plate): the
        # schema is Generic but the material is genuinely metal.
        if _bool_of(_find(asset, "generic_is_metal")):
            out["metallic"] = 1.0

        diffuse = _find_first(asset, _DIFFUSE_NAMES) or _scan_diffuse(asset)
        if diffuse is not None:
            color = _color_of(diffuse)
            asset_tint = _asset_tint(asset)
            dmap, dstate, draw = _bitmap_of(diffuse, doc, color=True)
            if dmap is not None:
                out.setdefault("maps", {})["diffuse"] = dmap
                _STATS["textured"] += 1
                if color is not None:
                    out["base_color"] = _clamp_rgb(_mul(color, asset_tint))
                # The appearance tint covers the whole look: on an image it
                # multiplies the image, on a plain colour the colour.
                if asset_tint:
                    dmap["tint"] = _mul(dmap.get("tint"), asset_tint)
                # Hardwood keeps its separate tint on the parent asset.
                if str(diffuse.Name) == "hardwood_color" \
                        and _bool_of(_find(asset, "hardwood_tint_enabled")):
                    hw = _color_of(_find(asset, "hardwood_tint_color"))
                    if hw:
                        dmap["tint"] = _mul(dmap.get("tint"), hw)
                if str(diffuse.Name) == "generic_diffuse":
                    fade = _double_of(_find(asset, "generic_diffuse_image_fade"))
                    if fade is not None:
                        dmap["fade"] = max(0.0, min(1.0, fade))
                _tidy_map(dmap)
            elif dstate in ("missing", "procedural"):
                # A texture was expected but did not make it in. Fall back to
                # the graphics colour, not the asset's (often white) render
                # colour - and do NOT apply the appearance tint (BimGo: the
                # shaded look must not be tinted twice).
                if shading_color is not None:
                    out["base_color"] = list(shading_color)
                    _STATS["fallback"] += 1
                if dstate == "missing":
                    _STATS["missing"] += 1
                    _log("texture missing for '%s': %s"
                         % (_mat_name(mat), draw or "?"))
                else:
                    _STATS["procedural"] += 1
            elif color is not None:
                out["base_color"] = _clamp_rgb(_mul(color, asset_tint))

        bump = _find_first(asset, _BUMP_NAMES)
        if bump is not None:
            bmap, _bstate, _braw = _bitmap_of(bump, doc)
            if bmap is not None:
                bmap["amount"] = _bump_amount(asset)
                out.setdefault("maps", {})["bump"] = bmap

        gloss = _double_of(_find_first(asset, _GLOSS_NAMES))
        if gloss is not None and 0.0 <= gloss <= 1.0:
            out["glossiness"] = gloss
            out["roughness"] = max(0.05, min(1.0, 1.0 - gloss))
        # Advanced / Physical materials carry roughness directly; it wins over
        # the glossiness approximation when both exist.
        rough = _double_of(_find_first(asset, _ROUGHNESS_NAMES))
        if rough is None:
            rough = _double_of(_find_ending(asset, "_roughness"))
        if rough is not None:
            out["roughness"] = max(0.0, min(1.0, rough))
        if klass == "mirror":
            # A mirror stays sharp whatever else the asset says.
            out["roughness"] = 0.05

        transp = _double_of(_find_first(asset, _TRANSPARENCY_NAMES))
        if transp is not None and transp > 0.0:
            out["transparency"] = max(0.0, min(1.0, transp))
        return out
    except Exception:
        _STATS["unreadable"] += 1
        return {}


def reset_stats():
    for key in list(_STATS):
        _STATS[key] = 0


def log_stats():
    """One concise line so a Load View log says whether textures actually made
    it - the first thing to check when a render comes out grey/white."""
    if not _STATS["materials"]:
        return
    print("Blendit: materials: %d read, %d textured, %d missing texture(s), "
          "%d procedural, %d shading-colour fallback(s), %d empty asset(s), "
          "%d unreadable"
          % (_STATS["materials"], _STATS["textured"], _STATS["missing"],
             _STATS["procedural"], _STATS["fallback"], _STATS["empty"],
             _STATS["unreadable"]))


def _mat_name(mat):
    try:
        return str(mat.Name)
    except Exception:
        return "material"


def _log(msg):
    try:
        print("Blendit: " + msg)
    except Exception:
        pass


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


def _find_ending(asset, suffix):
    """First property whose name ends with `suffix` (e.g. any ``_roughness``)."""
    try:
        for i in range(asset.Size):
            p = asset[i]
            if p is not None and str(p.Name).lower().endswith(suffix):
                return p
    except Exception:
        pass
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
        for key, klass in _SCHEMA_CLASS:
            if key in schema:
                return klass
    except Exception:
        pass
    return ""


# --- property readers ---------------------------------------------------------
def _color_of(prop):
    """AssetPropertyDoubleArray4d/3d -> [r, g, b] (protein colours are linear)."""
    try:
        vals = list(prop.GetValueAsDoubles())
        if len(vals) >= 3:
            return [float(vals[0]), float(vals[1]), float(vals[2])]
    except Exception:
        pass
    try:
        xyz = prop.GetValueAsXYZ()
        if xyz is not None:
            return [float(xyz.X), float(xyz.Y), float(xyz.Z)]
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


def _bool_of(prop):
    if prop is None:
        return False
    try:
        return bool(prop.Value)
    except Exception:
        return False


def _asset_tint(asset):
    """Revit's Appearance-tab tint (common_Tint_toggle + common_Tint_color)."""
    if not _bool_of(_find(asset, "common_Tint_toggle")):
        return None
    return _color_of(_find(asset, "common_Tint_color"))


def _bitmap_tint(asset):
    """Tint multiplier on a UnifiedBitmap: its own tint + RGB amount."""
    tint = [1.0, 1.0, 1.0]
    if _bool_of(_find(asset, "common_Tint_toggle")):
        c = _color_of(_find(asset, "common_Tint_color"))
        if c:
            tint = _mul(tint, c)
    amount = _double_of(_find(asset, "unifiedbitmap_RGBAmount"))
    if amount is not None and amount > 0.0:
        amount = min(amount, 4.0)
        tint = [tint[0] * amount, tint[1] * amount, tint[2] * amount]
    return tint


def _mul(a, b):
    if not a:
        return list(b) if b else None
    if not b:
        return list(a)
    return [float(a[0]) * float(b[0]), float(a[1]) * float(b[1]),
            float(a[2]) * float(b[2])]


def _clamp_rgb(c):
    return [max(0.0, min(1.0, float(c[0]))),
            max(0.0, min(1.0, float(c[1]))),
            max(0.0, min(1.0, float(c[2])))]


def _is_white(c):
    return (not c) or (abs(c[0] - 1.0) < 1e-6 and abs(c[1] - 1.0) < 1e-6
                       and abs(c[2] - 1.0) < 1e-6)


def _tidy_map(entry):
    """Keep optional map fields only when they actually do something."""
    if entry.get("tint") is not None and _is_white(entry["tint"]):
        entry.pop("tint", None)
    if not entry.get("invert"):
        entry.pop("invert", None)
    if entry.get("fade") is not None and entry["fade"] >= 0.999:
        entry.pop("fade", None)
    return entry


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
def _bitmap_of(prop, doc=None, color=False):
    """Connected UnifiedBitmap -> (map, state, raw).

    `map` is {"source_path", "scale_m", "offset_m", "rotation_deg"} with an
    absolute source_path (the exporter bundles it), or None. `state` is
    "none" (no image on the slot), "embedded" (found), "missing" (a path was
    stored but the file is not on this machine) or "procedural" (the slot is
    driven by a noise/checker asset, not a bitmap). `color=True` also reads the
    image tint / invert (meaningless on a bump map).
    """
    if not _has_connected(prop):
        return None, "none", None
    try:
        sub = prop.GetSingleConnectedAsset()
    except Exception:
        return None, "missing", None
    if sub is None:
        return None, "missing", None
    pathp = _find(sub, "unifiedbitmap_Bitmap")
    if pathp is None:
        return None, "procedural", None
    try:
        raw = pathp.Value
    except Exception:
        raw = None
    if not raw:
        return None, "none", None            # "" means no texture, not missing
    path = _resolve_texture_path(raw, doc)
    if not path:
        return None, "missing", str(raw)
    try:
        entry = {
            "source_path": path,
            # RealWorldScale is the image's physical size; UScale/VScale are
            # repeats across it. One repeat is Scale / repeats (BimGo's fix -
            # ignoring UScale made tiled materials render too large).
            "scale_m": [_distance_m(sub, "texture_RealWorldScaleX", 0.3)
                        / _uv_scale(sub, "texture_UScale"),
                        _distance_m(sub, "texture_RealWorldScaleY", 0.3)
                        / _uv_scale(sub, "texture_VScale")],
            "offset_m": [_distance_m(sub, "texture_RealWorldOffsetX", 0.0),
                         _distance_m(sub, "texture_RealWorldOffsetY", 0.0)],
            "rotation_deg": _double_of(_find(sub, "texture_WAngle")) or 0.0,
        }
        if color:
            tint = _bitmap_tint(sub)
            if not _is_white(tint):
                entry["tint"] = tint
            if _bool_of(_find(sub, "unifiedbitmap_Invert")):
                entry["invert"] = True
        return entry, "embedded", str(raw)
    except Exception:
        return None, "missing", str(raw)


def _uv_scale(asset, name):
    val = _double_of(_find(asset, name))
    if val is None or val <= 1e-6:
        return 1.0
    return val


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


# --- texture path discovery ---------------------------------------------------
# Revit appearance assets store paths relative to the Autodesk Material Library,
# to Revit's "Additional Render Appearance Paths", or beside the model. The old
# hard-coded four roots missed other installs and every custom path. Probe the
# real Common Files folders, read Revit.ini, and try the model folder + the
# library's numbered Mats folders by file name (the BimGo locator's stages).
def _texture_roots():
    if _ROOTS_CACHE["roots"] is not None:
        return _ROOTS_CACHE["roots"]
    roots = []
    for var in ("CommonProgramFiles(x86)", "CommonProgramFiles",
                "CommonProgramW6432"):
        base = os.environ.get(var)
        if not base:
            continue
        for sub in (r"Autodesk Shared\Materials\Textures",
                    r"Autodesk Shared\Materials"):
            _add_dir(roots, os.path.join(base, sub))
    for root in _TEXTURE_ROOTS:
        _add_dir(roots, root)
    _ROOTS_CACHE["roots"] = roots
    return roots


def _extra_texture_paths(doc):
    """Revit.ini's additional render appearance paths, cached by Revit year."""
    version = ""
    try:
        version = str(doc.Application.VersionNumber or "")
    except Exception:
        pass
    if version in _EXTRA_CACHE:
        return _EXTRA_CACHE[version]
    out = []
    appdata = os.environ.get("APPDATA")
    if version and appdata:
        ini = os.path.join(appdata, "Autodesk", "Revit",
                           "Autodesk Revit %s" % version, "Revit.ini")
        if os.path.isfile(ini):
            try:
                f = open(ini, "rb")
                try:
                    for line in f:
                        try:
                            text = line.decode("mbcs", "ignore")
                        except Exception:
                            text = line
                        eq = text.find("=")
                        if eq <= 0:
                            continue
                        name = text[:eq].lower()
                        if "appearance" not in name and "texture" not in name:
                            continue
                        for part in text[eq + 1:].replace("|", ";").split(";"):
                            _add_dir(out, os.path.expandvars(
                                part.strip().strip('"')))
                finally:
                    f.close()
            except Exception:
                pass
    _EXTRA_CACHE[version] = out
    return out


def _doc_folder(doc):
    try:
        path = doc.PathName
        if path:
            return os.path.dirname(str(path))
    except Exception:
        pass
    return None


def _add_dir(items, path):
    try:
        if path and os.path.isdir(path):
            path = os.path.normpath(path)
            if path not in items:
                items.append(path)
    except Exception:
        pass


def _split_alternatives(raw):
    try:
        pieces = str(raw).split("|")
    except Exception:
        pieces = []
    for piece in pieces:
        try:
            alt = os.path.expandvars(piece.strip().strip('"'))
            alt = alt.replace("/", os.sep)
        except Exception:
            continue
        if alt:
            yield alt


def _resolve_texture_path(raw, doc=None):
    """Resolve an asset bitmap path against every place Revit looks.

    Stages: absolute (environment expanded) -> Autodesk library roots ->
    Revit.ini additional paths -> the model folder -> the library's numbered
    Mats folders by file name. Cached per (raw, model folder)."""
    if not raw:
        return None
    folder = _doc_folder(doc)
    key = (str(raw), folder or "")
    if key in _PATH_CACHE:
        return _PATH_CACHE[key]
    roots = _texture_roots()
    extras = _extra_texture_paths(doc)
    found = None
    for alt in _split_alternatives(raw):
        rooted = os.path.isabs(alt)
        name = os.path.basename(alt)
        if rooted and os.path.isfile(alt):
            found = alt
            break
        if not rooted:
            for root in roots:
                cand = os.path.join(root, alt)
                if os.path.isfile(cand):
                    found = cand
                    break
            if found:
                break
        for extra in extras:
            if not rooted:
                cand = os.path.join(extra, alt)
                if os.path.isfile(cand):
                    found = cand
                    break
            if name:
                cand = os.path.join(extra, name)
                if os.path.isfile(cand):
                    found = cand
                    break
        if found:
            break
        if folder:
            if not rooted:
                cand = os.path.join(folder, alt)
                if os.path.isfile(cand):
                    found = cand
                    break
            if name:
                cand = os.path.join(folder, name)
                if os.path.isfile(cand):
                    found = cand
                    break
        if found:
            break
        if name:
            for root in roots:
                for n in ("1", "2", "3", "4"):
                    cand = os.path.join(root, n, "Mats", name)
                    if os.path.isfile(cand):
                        found = cand
                        break
                if found:
                    break
                cand = os.path.join(root, name)
                if os.path.isfile(cand):
                    found = cand
                    break
        if found:
            break
    _PATH_CACHE[key] = found
    return found


def reset_texture_cache():
    """Forget discovered roots/paths (tests; a live Revit session normally keeps
    them for the extraction)."""
    _ROOTS_CACHE["roots"] = None
    _EXTRA_CACHE.clear()
    _PATH_CACHE.clear()
