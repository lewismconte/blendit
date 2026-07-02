"""Pipeline step: build sun + sky from the SceneSpec `sun` / `world`.

The "sun + sky" split the brief calls for: a Nishita physical sky provides ambient
+ reflections (its own sun disc turned OFF to avoid a double sun), and an explicit
Sun lamp provides the key light and controllable shadow softness.

Sun angles - accurate shadows matter to architects, so the priority is:
  1. `direct` azimuth/altitude from Revit, CROSS-CHECKED against the
     location+time calculation when both exist (a view-relative or
     convention-drifted extraction must never silently skew the shadows);
  2. `geographic` lat/long + date/time -> pipeline/sun_calc.py (Melbourne in
     Revit is Melbourne here, at the same time of day);
  3. an explicit `vector`;
  4. a pleasant default only when the bundle carries nothing better.
"""
import math

import bpy
import mathutils

_DEFAULT_ALT = 55.0   # degrees above horizon
_DEFAULT_AZ = 150.0   # degrees, from North (+Y) clockwise toward East (+X)
_MIN_SUN_ALT = 3.0    # keep golden-hour studies honest; only lift night suns
_SKY_GAIN = 0.4       # tame the (very bright) physical sky so it doesn't wash out
_SUN_GAIN = 5.0       # sun as the dominant key -> contrast + crisp shadows


def setup_world(spec, scale):
    sun = spec.get("sun", {})
    world_spec = spec.get("world", {})
    alt_deg, az_deg = _sun_angles(sun)

    # A below-horizon sun (a midnight-dated study) renders a black sky. Lift it
    # just above the horizon so the render is usable (azimuth kept, so the
    # shadow direction is still the model's). The floor is low (3 deg) on
    # purpose: architects do golden-hour studies, and faking the altitude
    # would fake the shadow lengths.
    if alt_deg < _MIN_SUN_ALT:
        print("[Blendit] sun altitude %.1f deg is below the horizon; lifting to "
              "%.1f so the render isn't night (azimuth kept)." % (alt_deg, _MIN_SUN_ALT))
        alt_deg = _MIN_SUN_ALT

    _build_sky(world_spec, alt_deg, az_deg)
    _build_sun_lamp(sun, alt_deg, az_deg)


def _geographic_angles(sun):
    """(altitude, azimuth) from lat/long + date + time via sun_calc, or None
    when the spec doesn't carry a complete location + moment."""
    lat, lon = sun.get("latitude"), sun.get("longitude")
    date, time = sun.get("date"), sun.get("time")
    if lat is None or lon is None or not date or not time:
        return None
    try:
        from . import sun_calc
        p = str(date).split("-")
        doy = sun_calc.day_of_year(int(p[1]), int(p[2]))
        t = str(time).split(":")
        hour = int(t[0]) + (int(t[1]) / 60.0 if len(t) > 1 else 0.0)
        tz = sun.get("timezone")
        # Unknown timezone: lon/15 cancels the longitude correction, treating
        # `time` as local solar time - the honest approximation.
        tz = float(tz) if tz is not None else float(lon) / 15.0
        az, alt = sun_calc.solar_position(float(lat), float(lon), doy, hour, tz)
        return alt, az
    except Exception:
        return None


def _az_delta(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _sun_angles(sun):
    geo = _geographic_angles(sun)
    if sun.get("altitude_degrees") is not None and sun.get("azimuth_degrees") is not None:
        alt, az = float(sun["altitude_degrees"]), float(sun["azimuth_degrees"])
        if geo is not None:
            galt, gaz = geo
            # Revit's own angles and the location+time calculation should
            # agree. A big divergence means the direct extraction is suspect
            # (view-relative angles / convention drift) - trust the place and
            # the clock, never silently skew the shadows.
            if abs(galt - alt) > 10.0 or _az_delta(gaz, az) > 20.0:
                print("[Blendit] Revit sun angles (alt %.0f / az %.0f) disagree "
                      "with the site location + time (alt %.0f / az %.0f); "
                      "using location + time." % (alt, az, galt, gaz))
                return geo
        return alt, az
    if geo is not None:
        return geo
    if str(sun.get("mode", "")) == "vector" and sun.get("direction"):
        d = mathutils.Vector(sun["direction"]).normalized()  # points FROM sun TO scene
        to_sun = -d
        alt = math.degrees(math.asin(max(-1.0, min(1.0, to_sun.z))))
        az = math.degrees(math.atan2(to_sun.x, to_sun.y)) % 360.0
        return alt, az
    return _DEFAULT_ALT, _DEFAULT_AZ


def _physical_sky_type(sky_node):
    """Prefer the Nishita-family physical sky, robust to the 4.x -> 5.0 rename."""
    items = [i.identifier
             for i in sky_node.bl_rna.properties["sky_type"].enum_items]
    for candidate in ("NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING",
                      "HOSEK_WILKIE", "PREETHAM"):
        if candidate in items:
            return candidate
    return items[0]


def _to_sun_vector(alt_deg, az_deg):
    alt = math.radians(alt_deg)
    az = math.radians(az_deg)
    # +Y North, +X East, +Z up
    return mathutils.Vector((math.cos(alt) * math.sin(az),
                             math.cos(alt) * math.cos(az),
                             math.sin(alt))).normalized()


def _build_sky(world_spec, alt_deg, az_deg):
    sky_type = str(world_spec.get("sky_type", "nishita"))
    strength = float(world_spec.get("strength", 1.0))

    # Reuse the scene's world (clear + rebuild its nodes) instead of making a new
    # one each call - a fresh world per live mode-switch would orphan the old one
    # (World.001, .002, ...). Matches npr.set_world_flat / _helpers.set_neutral_world.
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (300, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.location = (100, 0)
    bg.inputs["Strength"].default_value = strength * _SKY_GAIN
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    if sky_type == "nishita":
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.location = (-200, 0)
        # The physical sky enum churned: 4.x exposes 'NISHITA'; Blender 5.0 replaced
        # it with 'MULTIPLE_SCATTERING' (+ 'SINGLE_SCATTERING'). Resolve at runtime.
        sky.sky_type = _physical_sky_type(sky)
        if hasattr(sky, "sun_disc"):
            sky.sun_disc = False                # the Sun lamp is the sun
        if hasattr(sky, "sun_elevation"):
            sky.sun_elevation = math.radians(alt_deg)
        if hasattr(sky, "sun_rotation"):
            sky.sun_rotation = math.radians(az_deg)
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    elif sky_type == "solid":
        albedo = world_spec.get("ground_albedo", [0.3, 0.3, 0.3])
        bg.inputs["Color"].default_value = (albedo[0], albedo[1], albedo[2], 1.0)
    else:
        # TODO (Phase 1): hdri sky_type -> ShaderNodeTexEnvironment from world.hdri_uri.
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1.0)


def _build_sun_lamp(sun, alt_deg, az_deg):
    # Idempotent: drop any prior BIR sun so re-running (live mode switch) doesn't
    # stack lamps.
    for obj in list(bpy.data.objects):
        if obj.name == "Sun" and getattr(obj, "data", None) is not None \
                and getattr(obj.data, "type", None) == "SUN":
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

    light = bpy.data.lights.new("Sun", type="SUN")
    light.angle = math.radians(float(sun.get("angle_degrees", 0.526)))
    light.energy = _SUN_GAIN * float(sun.get("strength", 1.0))
    color = sun.get("color")
    if color:
        light.color = (color[0], color[1], color[2])

    obj = bpy.data.objects.new("Sun", light)
    bpy.context.scene.collection.objects.link(obj)
    # Sun lamp emits along its local -Z; we want rays travelling FROM the sun INTO
    # the scene, i.e. local -Z aligned with -to_sun.
    to_sun = _to_sun_vector(alt_deg, az_deg)
    obj.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    return obj
