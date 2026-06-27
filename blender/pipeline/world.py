"""Pipeline step: build sun + sky from the SceneSpec `sun` / `world`.

The "sun + sky" split the brief calls for: a Nishita physical sky provides ambient
+ reflections (its own sun disc turned OFF to avoid a double sun), and an explicit
Sun lamp provides the key light and controllable shadow softness.

Sun angles: `direct` mode (azimuth/altitude) and `vector` mode are honored now.
`geographic` mode falls back to a sensible default — accurate solar placement
(via Revit's own Altitude/Azimuth, or Blender's Sun Position add-on) is a Phase 1
wiring task. See TODO below.
"""
import math

import bpy
import mathutils

_DEFAULT_ALT = 55.0   # degrees above horizon
_DEFAULT_AZ = 150.0   # degrees, from North (+Y) clockwise toward East (+X)
_MIN_SUN_ALT = 15.0   # below this the Nishita sky goes black (twilight/night)
_SKY_GAIN = 0.4       # tame the (very bright) physical sky so it doesn't wash out
_SUN_GAIN = 5.0       # sun as the dominant key -> contrast + crisp shadows


def setup_world(spec, scale):
    sun = spec.get("sun", {})
    world_spec = spec.get("world", {})
    alt_deg, az_deg = _sun_angles(sun)

    # A near-horizon Revit sun renders a black twilight sky + raking light. Lift it
    # to a daylight angle so the default render is usable (keeps the azimuth, so the
    # shadow direction is still the model's). Set a daytime sun in Revit for an
    # accurate study.
    if alt_deg < _MIN_SUN_ALT:
        print("[Blendit] sun altitude %.1f deg is near/below the horizon; lifting to "
              "%.1f for a daylit render (azimuth kept)." % (alt_deg, _MIN_SUN_ALT))
        alt_deg = _MIN_SUN_ALT

    _build_sky(world_spec, alt_deg, az_deg)
    _build_sun_lamp(sun, alt_deg, az_deg)


def _sun_angles(sun):
    mode = str(sun.get("mode", "geographic"))
    if sun.get("altitude_degrees") is not None and sun.get("azimuth_degrees") is not None:
        return float(sun["altitude_degrees"]), float(sun["azimuth_degrees"])
    if mode == "vector" and sun.get("direction"):
        d = mathutils.Vector(sun["direction"]).normalized()  # points FROM sun TO scene
        to_sun = -d
        alt = math.degrees(math.asin(max(-1.0, min(1.0, to_sun.z))))
        az = math.degrees(math.atan2(to_sun.x, to_sun.y)) % 360.0
        return alt, az
    # TODO (Phase 1): geographic -> angles. Revit supplies Altitude/Azimuth
    # directly from SunAndShadowSettings, so the extractor can fill direct mode;
    # alternatively drive Blender's Sun Position add-on from lat/long + date/time.
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
