"""Artificial lighting fixtures -> contract `lights` list.

WHAT ARCHITECTS NEED: interiors that actually light up. Revit fixtures carry
photometrics (intensity, colour temperature, beam angles); we translate what
we can read reliably and let the Blender side own the watts conversion.

Two sources, mirroring geometry extraction:
  * PRIMARY: view_export.OnLight already captured every DISPLAYED light (world
    placement + element ref) while walking the view - WYSIWYG, links included.
    resolve_lights() reads photometrics off each fixture element.
  * FALLBACK: extract_lights_collector() walks OST_LightingFixtures in the
    view (host only) for the non-CustomExporter / 2D path, or as a safety net
    when OnLight captured nothing on a view that clearly has fixtures.

Photometric parameter NAMES/UNITS vary across Revit versions and are read
DEFENSIVELY (candidate BuiltInParameter lists resolved via getattr, every read
guarded, unknowns skipped). A fixture that yields nothing still emits a sane
default point light at its position so it never silently vanishes. Verify the
real names/units on a live model and tighten - the established pattern.

IronPython 2.7 + pure ASCII. Keep it that way.
"""
from bir_extract import _compat

DB = _compat.DB

# Candidate BuiltInParameter names per photometric quantity, tried IN ORDER
# (first one with a value wins). Concrete value params first so we read a real
# quantity, not the "which unit" flag. getattr skips any this Revit lacks, so
# extra candidates are harmless. NOTE: FBX_LIGHT_LIMUNOUS_FLUX is spelled with
# that typo IN THE REVIT API itself (verified) - keep it. `intensity_unit` is
# derived from WHICH param matched, so the Blender watts gain picks the right
# conversion.
_INTENSITY_BIPS = ("FBX_LIGHT_LIMUNOUS_FLUX",      # luminous flux (lm) - API typo
                   "FBX_LIGHT_LUMINOUS_FLUX",       # (correct spelling, just in case)
                   "FBX_LIGHT_ILLUMINANCE",         # lux
                   "FBX_LIGHT_INTENSITY",           # luminous intensity (cd)
                   "FBX_LIGHT_WATTAGE",             # electrical watts
                   "FBX_LIGHT_INITIAL_INTENSITY")   # last: may be a unit flag
_CCT_BIPS = ("FBX_LIGHT_INITIAL_COLOR_TEMPERATURE",  # Kelvin (Double) - verified
             "FBX_LIGHT_COLOR_TEMPERATURE", "FBX_LIGHT_TEMPERATURE")
_BEAM_BIPS = ("FBX_LIGHT_SPOT_BEAM_ANGLE",)
_FIELD_BIPS = ("FBX_LIGHT_SPOT_FIELD_ANGLE",)
_DIM_BIPS = ("FBX_LIGHT_DIMMING_VALUE", "FBX_LIGHT_DIMMING")

_DEG = 57.29577951308232        # 180/pi
_DEFAULT_RADIUS_M = 0.05


def _bip(name):
    """Resolve a BuiltInParameter enum by NAME, or None if this Revit lacks it."""
    if DB is None:
        return None
    return getattr(DB.BuiltInParameter, name, None)


def _read_double(el, names):
    """First readable AsDouble() among candidate BuiltInParameters on the element
    (then its type). Returns (value, matched_name) or (None, None)."""
    if el is None:
        return None, None
    typ = None
    try:
        typ = el.Document.GetElement(el.GetTypeId())
    except Exception:
        typ = None
    for name in names:
        bip = _bip(name)
        if bip is None:
            continue
        for holder in (el, typ):
            if holder is None:
                continue
            try:
                p = holder.get_Parameter(bip)
                if p is not None and p.HasValue:
                    return p.AsDouble(), name
            except Exception:
                pass
    return None, None


def _light_dict(lid, pos_ft, aim, el, log):
    """Build one contract light dict from a fixture element + captured placement."""
    intensity, iname = _read_double(el, _INTENSITY_BIPS)
    beam, _ = _read_double(el, _BEAM_BIPS)
    field, _ = _read_double(el, _FIELD_BIPS)
    cct, cname = _read_double(el, _CCT_BIPS)
    dim, _ = _read_double(el, _DIM_BIPS)

    beam_deg = (beam * _DEG) if beam else None      # Revit angles are radians
    field_deg = (field * _DEG) if field else None
    is_spot = (field_deg is not None and field_deg < 179.0) or \
              (beam_deg is not None and beam_deg < 179.0)

    # CCT sanity: a plausible Kelvin range; anything else is some other encoding
    # we don't understand yet (logged, left null so Blender uses a neutral lamp).
    color_kelvin = None
    if cct is not None and 1000.0 <= cct <= 20000.0:
        color_kelvin = cct

    on = True
    if dim is not None and dim <= 0.0001:
        on = False

    light = {
        "id": lid,
        "type": "spot" if is_spot else "point",
        "position": [pos_ft[0], pos_ft[1], pos_ft[2]],
        "direction": list(aim) if aim else [0.0, 0.0, -1.0],
        "intensity": float(intensity) if intensity is not None else 0.0,
        "intensity_unit": _unit_hint(iname),
        "color_kelvin": color_kelvin,
        "color": None,
        "spot_beam_deg": beam_deg,
        "spot_field_deg": field_deg,
        "radius_m": _DEFAULT_RADIUS_M,
        "on": on,
    }
    if log is not None:
        log.append("light %s: type=%s intensity=%s(%s) cct=%s(%s) beam=%s field=%s"
                   % (lid, light["type"], light["intensity"], iname,
                      color_kelvin, cname, beam_deg, field_deg))
    return light


def _unit_hint(param_name):
    if not param_name:
        return ""
    if "FLUX" in param_name or "LIMUNOUS" in param_name or "LUMEN" in param_name:
        return "lm"      # LIMUNOUS is the Revit API's own misspelling of luminous
    if "ILLUMINANCE" in param_name:
        return "lx"
    if "WATTAGE" in param_name:
        return "W"
    return "cd"          # Revit's INTENSITY is luminous intensity (candela)


def _element(rec_doc, eid):
    try:
        return rec_doc.GetElement(eid)
    except Exception:
        return None


def _location_point(el):
    """Fixture insertion XYZ (feet, its document's model coords), or None. This
    is the fixture's real placement in the building - spread across the plan -
    unlike the light node's family-local transform."""
    try:
        p = el.Location.Point           # LocationPoint (FamilyInstance fixtures)
        return p
    except Exception:
        return None


def _world_position(el, link_xf):
    """Location.Point, lifted through the LINK transform for linked fixtures
    (Location is already in the link document's model coords, so ONLY the link
    transform is applied - never the walk's instance transform, which would
    double-transform: the same rule OnRPC follows for trees)."""
    p = _location_point(el)
    if p is None:
        return None
    if link_xf is not None:
        try:
            p = link_xf.OfPoint(p)
        except Exception:
            pass
    return (p.X, p.Y, p.Z)


def _world_aim(el, link_xf):
    """Fixture aim direction (unit-ish), lifted through the link transform. Most
    ceiling fixtures shine DOWN; use the family's FacingOrientation when it reads
    downward-ish, else straight down. Direction is only a rotation, so apply the
    link transform's basis (OfVector), not OfPoint."""
    aim = None
    try:
        f = el.FacingOrientation          # family facing, model coords
        if abs(f.X) + abs(f.Y) + abs(f.Z) > 1e-6:
            aim = f
    except Exception:
        aim = None
    if aim is not None and link_xf is not None:
        try:
            aim = link_xf.OfVector(aim)
        except Exception:
            pass
    if aim is None:
        return (0.0, 0.0, -1.0)
    # A fixture "facing" is often its up/normal; a ceiling light should light the
    # room BELOW. If the facing points up, flip it down.
    z = aim.Z
    v = (aim.X, aim.Y, aim.Z)
    if z > 0.05:
        v = (-aim.X, -aim.Y, -aim.Z)
    return v


def resolve_lights(light_refs, host_doc, log=None):
    """-> list[light dict] from the OnLight captures. Each ref:
    {doc, scope, eid, link_xf}. Position from the element's Location.Point,
    photometrics from its parameters."""
    out = []
    if not light_refs:
        return out
    n = 0
    for rec in light_refs:
        try:
            rdoc = rec.get("doc") or host_doc
            eid = rec.get("eid")
            el = _element(rdoc, eid) if eid is not None else None
            if el is None:
                continue
            link_xf = rec.get("link_xf")
            pos = _world_position(el, link_xf)
            if pos is None:
                continue                     # no placement -> can't place a lamp
            aim = _world_aim(el, link_xf)
            n += 1
            out.append(_light_dict("light_%d" % n, pos, aim, el, log))
        except Exception:
            pass
    return out


def extract_lights_collector(doc, view, log=None):
    """Fallback: host lighting fixtures visible in `view` (no CustomExporter).
    Position/aim from the element; photometrics as in resolve_lights."""
    out = []
    if DB is None:
        return out
    try:
        cat = getattr(DB.BuiltInCategory, "OST_LightingFixtures", None)
        if cat is None:
            return out
        col = (DB.FilteredElementCollector(doc, view.Id)
               .OfCategory(cat).WhereElementIsNotElementType())
    except Exception:
        return out
    n = 0
    for el in col:
        try:
            pos = _world_position(el, None)     # host: no link transform
            if pos is None:
                continue
            aim = _world_aim(el, None)
            n += 1
            out.append(_light_dict("light_%d" % n, pos, aim, el, log))
        except Exception:
            pass
    return out
