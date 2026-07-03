"""Shared helpers for the render-mode presets (Blender side).

These poke at the world / sun / freestyle that build_scene already created (the
Sun lamp is named "Sun"; the world has Background + Sky Texture nodes), so presets
can shape the look without rebuilding the scene.
"""
import bpy


def world_background():
    w = bpy.context.scene.world
    if not w or not w.use_nodes:
        return None
    for n in w.node_tree.nodes:
        if n.type == "BACKGROUND":
            return n
    return None


def set_world_strength(absolute):
    bg = world_background()
    if bg is not None:
        bg.inputs["Strength"].default_value = float(absolute)


def sun_object():
    o = bpy.data.objects.get("Sun")
    if o is not None and getattr(o, "data", None) is not None \
            and o.data.type == "SUN":
        return o
    return None


def set_sun_energy(absolute):
    s = sun_object()
    if s is not None:
        s.data.energy = float(absolute)


def disable_freestyle():
    # NPR now uses Grease Pencil Line Art (live in the viewport); presets call this
    # defensively so a leftover Freestyle pass never doubles up on the outlines.
    bpy.context.scene.render.use_freestyle = False


# --- per-mode look helpers (each lit preset owns its view + lighting) --------
def set_view(transform="AgX", exposure=0.0, look="None"):
    """View transform + exposure for this mode. AgX = filmic (realistic/specular);
    Standard keeps white white (the clay / massing modes)."""
    vs = bpy.context.scene.view_settings
    try:
        vs.view_transform = transform
    except Exception:
        vs.view_transform = "Standard"
    vs.exposure = float(exposure)
    try:
        vs.look = look
    except Exception:
        pass


def set_neutral_world(value=0.85, strength=1.0):
    """Flat neutral-grey environment - no blue sky cast. The clay/white/shadow
    massing modes use this so white reads white and shadows stay neutral."""
    w = bpy.context.scene.world
    if w is None:
        w = bpy.data.worlds.new("World")
        bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (300, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (value, value, value, 1.0)
    bg.inputs["Strength"].default_value = float(strength)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def set_ground_tone(value):
    """Recolour the shadow-catcher ground (so it matches the mode's palette)."""
    g = bpy.data.objects.get("BIR_Ground")
    if g is None or not g.data.materials:
        return
    m = g.data.materials[0]
    if m.use_nodes:
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                n.inputs["Base Color"].default_value = (value, value, value, 1.0)


def set_ground_finish(value, roughness):
    """Ground colour + finish in one call (the showroom's dark glossy floor)."""
    g = bpy.data.objects.get("BIR_Ground")
    if g is None or not g.data.materials:
        return
    m = g.data.materials[0]
    if m.use_nodes:
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                n.inputs["Base Color"].default_value = (value, value, value, 1.0)
                n.inputs["Roughness"].default_value = float(roughness)


def set_studio_world(strength=1.0):
    """A dark studio-gradient environment with a glowing horizon band - the
    showroom backdrop. Near-black floor and zenith so the scene goes moody;
    the bright band is what glossy surfaces catch as reflections."""
    w = bpy.context.scene.world
    if w is None:
        w = bpy.data.worlds.new("World")
        bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (400, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.location = (200, 0)
    bg.inputs["Strength"].default_value = float(strength)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-600, 0)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-420, 0)
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    # Direction Z (-1..1) -> ramp position (0..1): 0.5 is the horizon.
    remap = nt.nodes.new("ShaderNodeMath")
    remap.operation = "MULTIPLY_ADD"
    remap.location = (-260, 0)
    remap.inputs[1].default_value = 0.5
    remap.inputs[2].default_value = 0.5
    nt.links.new(sep.outputs["Z"], remap.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-80, 0)
    cr = ramp.color_ramp
    stops = ((0.00, 0.015), (0.42, 0.03), (0.50, 0.75),   # the horizon glow
             (0.58, 0.07), (1.00, 0.02))
    els = cr.elements
    els[0].position, els[0].color = stops[0][0], (stops[0][1],) * 3 + (1.0,)
    els[1].position, els[1].color = stops[1][0], (stops[1][1],) * 3 + (1.0,)
    for pos, val in stops[2:]:
        e = els.new(pos)
        e.color = (val,) * 3 + (1.0,)
    nt.links.new(remap.outputs["Value"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])


def set_sun_softness(degrees):
    """Sun angular size -> shadow softness. 0.5 deg = crisp (real sun); larger =
    softer, diffuse shadows."""
    import math
    s = sun_object()
    if s is not None:
        s.data.angle = math.radians(max(0.0, float(degrees)))


def set_glossiness(loaded, roughness):
    """Override roughness on every imported material (the Specular/Lookdev knob)."""
    r = max(0.0, min(1.0, float(roughness)))
    for obj in loaded.node_to_object.values():
        if getattr(obj, "type", None) != "MESH":
            continue
        for m in obj.data.materials:
            if m is not None and m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == "BSDF_PRINCIPLED":
                        n.inputs["Roughness"].default_value = r


def clear_npr():
    """Remove NPR overlays (Line Art, hidden ground, Freestyle) so a rendered
    mode starts clean - matters when switching modes live."""
    disable_freestyle()
    from .. import npr
    npr.remove_line_art()
    npr.show_ground()
