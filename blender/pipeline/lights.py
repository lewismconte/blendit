"""Artificial lights: the contract `lights` list -> functional Blender lamps.

Interiors need their own fixtures - sky + sun alone leave a room black. This
rebuilds the Revit fixtures the bundle carries (bir_extract/lights.py) as
point / spot lamps in a `BIR_Lights` collection, so lit modes (realistic /
specular) actually illuminate the space.

Photometric honesty: Revit's raw intensity comes in mixed units (cd / lm / lx /
W) and Blender lamp `energy` is radiant watts. A physically exact conversion is
out of scope for v1, so - exactly like world._SUN_GAIN is an empirical key
gain, not a photometric derivation - we map each unit to watts with a tunable
constant tuned to light a typical room, then expose a global multiplier
(Live View's Lights strength). Colour temperature -> blackbody RGB in-code.

Lifecycle mirrors the sun lamp: built fresh in prepare_scene (after the .blend
cache boundary), idempotent so a live mode-switch never stacks lamps. Per-mode
visibility is set by the presets (lit modes show, drawing/clay modes hide, since
interior lamps would wash out the Shader-to-RGB tone the NPR modes derive); the
Live View master toggle overrides in any mode.
"""
import math

import bpy

COLLECTION = "BIR_Lights"

# Modes that show artificial fixtures BY DEFAULT (the photoreal / lookdev looks,
# where interior lighting matters). Every other mode hides them by default -
# interior lamps blow out the sun-derived tone the drawing / clay modes rely on -
# but the Live View master toggle can override in any mode.
DEFAULT_ON_MODES = ("realistic", "specular")


def default_visible_for(mode):
    return str(mode) in DEFAULT_ON_MODES

# Empirical watts-per-unit gains (see module docstring). Tuned so a typical
# ceiling downlight reads as a real interior light, dialled by the Live slider.
_GAIN = {
    "cd": 0.02,      # luminous intensity (candela) - Revit's default INTENSITY
    "lm": 0.004,     # luminous flux (lumens)
    "lx": 0.02,      # illuminance (lux)
    "W":  1.0,       # electrical wattage - already power-ish
    "":   0.02,      # unknown unit -> treat like candela
}
_FALLBACK_WATTS = 25.0     # a fixture that reported no usable intensity
_MIN_WATTS = 1.0
_MAX_WATTS = 2000.0        # clamp a mis-parsed unit from nuking the render


def _kelvin_to_rgb(kelvin):
    """Correlated colour temperature -> linear RGB (Tanner Helland approximation,
    normalized to ~1.0 max). Good enough for a warm/cool lamp tint."""
    t = max(1000.0, min(40000.0, float(kelvin))) / 100.0
    if t <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661 if t > 0 else 0.0
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
    if t >= 66.0:
        b = 255.0
    elif t <= 19.0:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    srgb = [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    # to linear (the lamp .color is linear)
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            for c in srgb]


def _watts(light):
    unit = str(light.get("intensity_unit", ""))
    raw = float(light.get("intensity", 0.0) or 0.0)
    if raw <= 0.0:
        return _FALLBACK_WATTS
    w = raw * _GAIN.get(unit, _GAIN[""])
    return max(_MIN_WATTS, min(_MAX_WATTS, w))


def _get_collection():
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    return coll


def _clear():
    """Remove any prior BIR lamps + the collection (idempotent rebuild)."""
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        return
    for obj in list(coll.objects):
        data = obj.data
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
        try:
            if data is not None and data.users == 0:
                bpy.data.lights.remove(data)
        except Exception:
            pass
    try:
        bpy.context.scene.collection.children.unlink(coll)
    except Exception:
        pass
    try:
        if coll.users == 0:
            bpy.data.collections.remove(coll)
    except Exception:
        pass


def setup_lights(spec, scale=1.0):
    """Build the BIR_Lights collection from spec['lights']. No-op (and cleans up
    any stale lamps) when the bundle carries none."""
    _clear()
    lights = spec.get("lights") or []
    if not lights:
        return None
    coll = _get_collection()
    scale = float(scale)
    made = 0
    for i, L in enumerate(lights):
        try:
            _build_one(coll, L, i, scale)
            made += 1
        except Exception:
            pass
    return coll if made else None


def _build_one(coll, L, i, scale):
    kind = "SPOT" if str(L.get("type")) == "spot" else "POINT"
    name = "%s_%s" % (COLLECTION, L.get("id", "l%d" % i))
    data = bpy.data.lights.new(name, type=kind)
    data.energy = _watts(L)

    ck = L.get("color_kelvin")
    col = L.get("color")
    if ck:
        data.color = _kelvin_to_rgb(ck)
    elif col:
        data.color = (float(col[0]), float(col[1]), float(col[2]))

    try:
        data.shadow_soft_size = max(0.005, float(L.get("radius_m", 0.05)))
    except Exception:
        pass

    if kind == "SPOT":
        field = L.get("spot_field_deg")
        beam = L.get("spot_beam_deg")
        if field:
            data.spot_size = math.radians(min(179.0, float(field)))
        else:
            data.spot_size = math.radians(90.0)
        # blend = how soft the edge is; from the beam/field ratio when we have both
        if field and beam and float(field) > 0.0:
            data.spot_blend = max(0.0, min(1.0, 1.0 - float(beam) / float(field)))
        else:
            data.spot_blend = 0.15

    obj = bpy.data.objects.new(name, data)
    coll.objects.link(obj)

    pos = L.get("position") or [0.0, 0.0, 0.0]
    obj.location = (pos[0] * scale, pos[1] * scale, pos[2] * scale)

    if kind == "SPOT":
        d = L.get("direction") or [0.0, 0.0, -1.0]
        vec = _mathutils_vec(d)
        if vec is not None and vec.length > 1e-6:
            # spot emits down local -Z; aim -Z along the light direction
            obj.rotation_euler = vec.to_track_quat("-Z", "Y").to_euler()
    return obj


def _mathutils_vec(d):
    try:
        from mathutils import Vector
        return Vector((float(d[0]), float(d[1]), float(d[2])))
    except Exception:
        return None


# --- live controls ----------------------------------------------------------
def set_lights_visible(visible):
    """Show/hide the whole fixture collection in render + viewport."""
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        return
    for obj in coll.objects:
        obj.hide_render = not visible
        obj.hide_viewport = not visible


def set_lights_strength(mult):
    """Rescale every fixture's energy by `mult` relative to its extracted base.
    The base watts is stashed on the object so repeated slider moves don't
    compound."""
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        return
    m = max(0.0, float(mult))
    for obj in coll.objects:
        data = getattr(obj, "data", None)
        if data is None:
            continue
        base = obj.get("bir_base_watts")
        if base is None:
            base = data.energy
            obj["bir_base_watts"] = base
        data.energy = float(base) * m


def has_lights():
    coll = bpy.data.collections.get(COLLECTION)
    return coll is not None and len(coll.objects) > 0
