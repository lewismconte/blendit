"""NPR building blocks: Grease Pencil Line Art outlines + toon (cel) shading.

Line Art (GPv3 'LINEART' modifier, via the LINEART_SCENE add operator) renders in
the realtime EEVEE viewport AND the final image, so pen / sketch / cel lines
preview live as you navigate - unlike Freestyle, which is render-only.

All NPR modes run under EEVEE (Line Art previews live there; toon's Shader-to-RGB
is EEVEE-only).
"""
import math

import bpy

_GP_NAME = "BIR_LineArt"
_LINE_MAT = "BIR_Line"


# --- flat fill / world / ground (for the pen + sketch "paper" look) --------
def make_two_tone_material(shade_color, lit_color, threshold=0.5,
                           name="BIR_TwoTone"):
    """A hard lit/shade split fill: faces toward the light take `lit_color`,
    everything else melts into `shade_color`. Pair the shade with the paper
    colour for accent looks (white pencil on kraft). EEVEE-only
    (Shader-to-RGB), like the toon materials."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-300, 0)
    diff.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)
    s2 = nt.nodes.new("ShaderNodeShaderToRGB")
    s2.location = (-100, 0)
    nt.links.new(diff.outputs["BSDF"], s2.inputs["Shader"])
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    bw.location = (60, 0)
    nt.links.new(s2.outputs["Color"], bw.inputs["Color"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (220, 0)
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    cr.elements[0].position = 0.0
    cr.elements[0].color = (shade_color[0], shade_color[1], shade_color[2], 1.0)
    cr.elements[1].position = float(threshold)
    cr.elements[1].color = (lit_color[0], lit_color[1], lit_color[2], 1.0)
    nt.links.new(bw.outputs["Val"], ramp.inputs["Fac"])
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.location = (430, 0)
    nt.links.new(ramp.outputs["Color"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_flat_material(color=(0.95, 0.95, 0.95), name="BIR_Flat"):
    """A shadeless flat fill (emission) - no gradients, like ink on paper."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    emi.inputs["Strength"].default_value = 1.0
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def set_world_flat(color=(0.98, 0.98, 0.98), strength=1.0):
    w = bpy.context.scene.world
    if w is None:
        w = bpy.data.worlds.new("World")
        bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (200, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def set_camera_ray_world(visible=(0.96, 0.92, 0.82), ambient=0.06, strength=1.0,
                         gradient=None):
    """A world that shows a `visible` paper colour to the CAMERA but contributes
    only a dim neutral `ambient` to LIGHTING (via Light Path 'Is Camera Ray'). Lets a
    paper backdrop sit behind a scene lit almost entirely by the sun - a wide, clean
    light->shade range for posterised looks (riso) without a black sky.

    `gradient` (horizon_rgb, zenith_rgb) makes the CAMERA see a soft vertical wash
    (warm horizon at the bottom of frame -> cool zenith at the top, screen-space
    Window.Y) instead of the flat `visible` colour - the watercolour sky. LIGHTING
    still gets only the dim `ambient` either way."""
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
    lp = nt.nodes.new("ShaderNodeLightPath")
    lp.location = (-260, 220)
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.location = (0, 0)
    mix.inputs["Color1"].default_value = (ambient, ambient, ambient, 1.0)   # lighting rays
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(mix.outputs["Color"], bg.inputs["Color"])
    if gradient is None:
        mix.inputs["Color2"].default_value = (visible[0], visible[1], visible[2], 1.0)
        return
    # Vertical screen-space wash for the camera: Window.Y (reliable in EEVEE where
    # the world ray-direction coords aren't). Bottom of frame = warm horizon.
    horizon, zenith = gradient
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-600, -200)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-420, -200)
    nt.links.new(tc.outputs["Window"], sep.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-200, -200)
    ramp.color_ramp.interpolation = "EASE"
    ramp.color_ramp.elements[0].position = 0.42
    ramp.color_ramp.elements[0].color = tuple(horizon) + (1.0,)
    ramp.color_ramp.elements[1].position = 0.95
    ramp.color_ramp.elements[1].color = tuple(zenith) + (1.0,)
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["Color2"])


def _ground():
    return bpy.data.objects.get("BIR_Ground")


def hide_ground():
    g = _ground()
    if g is not None:
        g.hide_render = True
        g.hide_viewport = True


def show_ground():
    g = _ground()
    if g is not None:
        g.hide_render = False
        g.hide_viewport = False


def default_line_radius():
    """Default Line Art pen width, in world metres. A flat 0.05 reads best for
    architecture (the scene is imported to real metres), and looks cleaner than the
    old model-diagonal scaling. The Line Thickness slider tunes it per shot."""
    return 0.05


def set_flat_view():
    """NPR flat look: Standard view transform (white = white, black = black),
    neutral exposure - AgX would grey-out the flat fill + lines."""
    vs = bpy.context.scene.view_settings
    try:
        vs.view_transform = "Standard"
    except Exception:
        pass
    vs.exposure = 0.0
    try:
        vs.look = "None"
    except Exception:
        pass


# --- Line Art ---------------------------------------------------------------
def remove_line_art():
    obj = bpy.data.objects.get(_GP_NAME)
    if obj is None:
        return
    data = obj.data
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        return
    try:
        if data is not None and data.users == 0:
            bpy.data.grease_pencils.remove(data)
    except Exception:
        pass


def _lineart_mod(gp):
    for m in gp.modifiers:
        if m.type == "LINEART":
            return m
    return None


def _noise_mod(gp):
    for m in gp.modifiers:
        if m.type == "GREASE_PENCIL_NOISE":
            return m
    return None


def _length_mod(gp):
    for m in gp.modifiers:
        if m.type == "GREASE_PENCIL_LENGTH":
            return m
    return None


def _style_line_mat(mat, color):
    gpstyle = mat.grease_pencil
    gpstyle.color = (color[0], color[1], color[2], 1.0)
    # The Line Art default material ships with show_stroke OFF - strokes then
    # render with a dark fallback and every colour we set was invisible (only
    # noticed when Blueprint asked for WHITE lines). Assert the flags.
    try:
        gpstyle.show_stroke = True
        gpstyle.show_fill = False
    except Exception:
        pass


def _set_line_color(gp, color):
    for mat in gp.data.materials:
        if mat is not None and mat.grease_pencil is not None:
            _style_line_mat(mat, color)
            return
    mat = bpy.data.materials.new(_LINE_MAT)
    bpy.data.materials.create_gpencil_data(mat)
    _style_line_mat(mat, color)
    gp.data.materials.append(mat)


def setup_line_art(radius=0.05, color=(0.0, 0.0, 0.0), crease_deg=70.0,
                   thickness_factor=3.0, intersection=False):
    """Create the BIR Line Art object (one per scene). Returns the GP object."""
    remove_line_art()
    before = set(bpy.data.objects)
    bpy.ops.object.grease_pencil_add(type="LINEART_SCENE")
    # bpy.context.active_object isn't available in the restricted startup context;
    # find the newly created Grease Pencil object by diffing instead.
    gp = None
    for o in bpy.data.objects:
        if o not in before and o.type == "GREASEPENCIL":
            gp = o
            break
    if gp is None:
        gp = (getattr(bpy.context, "active_object", None)
              or getattr(bpy.context, "object", None))
    if gp is None:
        return None
    gp.name = _GP_NAME
    gp.data.name = _GP_NAME
    # Strokes are INK, not surfaces: GPv3 layers default to 'use lights',
    # which multiplies the stroke colour by the scene lighting - white lines
    # on a dark world rendered nearly black (found by Blueprint mode; it also
    # muted every Line Color slider pick under a dim world).
    try:
        if hasattr(gp, "use_grease_pencil_lights"):
            gp.use_grease_pencil_lights = False
    except Exception:
        pass
    for lay in gp.data.layers:
        try:
            lay.use_lights = False
        except Exception:
            pass
    _set_line_color(gp, color)

    m = _lineart_mod(gp)
    if m is not None:
        m.radius = radius
        m.use_contour = True       # silhouettes
        m.use_crease = True        # sharp edges
        m.use_material = False     # skip material boundaries (busy on detailed models)
        m.use_intersection = intersection
        try:
            m.crease_threshold = max(0.0, min(1.0, math.cos(math.radians(crease_deg))))
        except Exception:
            pass

    # A thickness modifier gives an extra, consistent boost over the world-space
    # radius (and a hook for the live thickness slider).
    try:
        tk = gp.modifiers.new("Thick", "GREASE_PENCIL_THICKNESS")
        tk.thickness_factor = thickness_factor
    except Exception:
        pass
    return gp


def set_line_art_radius(radius):
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None:
        return
    m = _lineart_mod(gp)
    if m is not None:
        m.radius = max(0.0001, float(radius))


def set_line_art_color(color):
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is not None:
        _set_line_color(gp, color)


def get_line_art_color():
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is not None:
        for mat in gp.data.materials:
            if mat is not None and mat.grease_pencil is not None:
                c = mat.grease_pencil.color
                return (c[0], c[1], c[2])
    return None


def get_line_art_radius():
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is not None:
        m = _lineart_mod(gp)
        if m is not None:
            return m.radius
    return None


def _active_lineart_mod():
    gp = bpy.data.objects.get(_GP_NAME)
    return _lineart_mod(gp) if gp is not None else None


def set_line_art_crease(deg):
    """Edges sharper than `deg` get a crease line. Higher deg = fewer interior
    lines (cleaner); lower = busier."""
    m = _active_lineart_mod()
    if m is not None:
        try:
            m.crease_threshold = max(0.0, min(1.0, math.cos(math.radians(deg))))
        except Exception:
            pass


def get_line_art_crease_deg():
    m = _active_lineart_mod()
    if m is not None:
        try:
            return math.degrees(math.acos(max(-1.0, min(1.0, m.crease_threshold))))
        except Exception:
            return None
    return None


def set_line_art_intersection(on):
    """Draw lines where separate meshes intersect (good for hard-surface, busy on
    very dense models)."""
    m = _active_lineart_mod()
    if m is not None:
        m.use_intersection = bool(on)


def set_line_art_occlusion(show_hidden):
    """Off = only front-facing visible lines (clean architectural look).
    On = also draw a couple of occluded layers (x-ray-ish interior edges)."""
    m = _active_lineart_mod()
    if m is None:
        return
    try:
        if show_hidden:
            m.use_multiple_levels = True
            m.level_start = 0
            m.level_end = 2
        else:
            m.use_multiple_levels = False
            m.level_start = 0
    except Exception:
        pass


def refresh_line_art():
    """Force the (unbaked) Line Art to re-trace for the current camera + settings.
    Line Art is camera-relative, so callers snap the camera to the view first.
    No-op when baked (a stray refresh must not un-mute a frozen result)."""
    m = _active_lineart_mod()
    if m is not None:
        if not m.show_viewport:    # baked / muted -> leave it frozen
            return
        try:                       # nudge a clean recompute on the next eval
            m.show_viewport = False
            m.show_viewport = True
        except Exception:
            pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


# --- bake / cache ----------------------------------------------------------
# Line Art is procedural: it re-traces on every depsgraph eval (mode switch,
# export, render, sometimes a slider drag) - the bulk of the "pen mode is
# sluggish" cost on detailed models. Baking freezes the current trace into stored
# strokes and mutes the modifier, so export / render / capture reuse it instead of
# recomputing. Regenerate un-freezes, re-traces for the new camera, and re-bakes.
def is_line_art_baked():
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None:
        return False
    m = _lineart_mod(gp)
    return m is not None and not m.show_viewport


def _copy_drawing(src, dst):
    """Copy strokes (points: position/radius/opacity + cyclic/material) from one GP
    drawing to another, replacing the destination's strokes."""
    if len(dst.strokes):
        dst.remove_strokes(indices=list(range(len(dst.strokes))))
    sizes = [len(s.points) for s in src.strokes]
    if not sizes:
        return
    dst.add_strokes(sizes)
    for i, s in enumerate(src.strokes):
        ds = dst.strokes[i]
        try:
            ds.cyclic = s.cyclic
            ds.material_index = s.material_index
        except Exception:
            pass
        for j, p in enumerate(s.points):
            dp = ds.points[j]
            dp.position = p.position
            dp.radius = p.radius
            dp.opacity = p.opacity
    try:
        dst.tag_positions_changed()
    except Exception:
        pass


# Line width is WORLD-space (a 0.05 m pen), so strokes near the camera project
# enormous in a deep street perspective - near-solid silhouettes. The clamp caps
# every point's SCREEN width at what a stroke shows at `_NEAR_CLAMP` metres:
# nearer points scale by distance/clamp (with a small floor so contact lines
# don't vanish); everything at or beyond the clamp distance is untouched.
# 0 disables. Depth cue, when the user enables it, REPLACES this policy (it
# reassigns radii wholesale as an artistic choice).
_NEAR_CLAMP = [10.0]
_CLAMP_FLOOR = 0.12


def set_near_clamp(metres):
    _NEAR_CLAMP[0] = max(0.0, float(metres))


def get_near_clamp():
    return _NEAR_CLAMP[0]


def clamp_screen_width():
    """Scale down BAKED stroke radii near the camera (see _NEAR_CLAMP above)."""
    near = _NEAR_CLAMP[0]
    if near <= 0.0:
        return
    gp = bpy.data.objects.get(_GP_NAME)
    cam = bpy.context.scene.camera
    if gp is None or cam is None:
        return
    try:
        cam_pos = cam.matrix_world.translation
        mw = gp.matrix_world
        for lay in gp.data.layers:
            for frame in lay.frames:
                for s in frame.drawing.strokes:
                    for p in s.points:
                        d = (mw @ p.position - cam_pos).length
                        if d < near:
                            p.radius = p.radius * max(d / near, _CLAMP_FLOOR)
                try:
                    frame.drawing.tag_positions_changed()
                except Exception:
                    pass
    except Exception as ex:
        print("Blendit: clamp_screen_width failed: %s" % ex)


def bake_line_art():
    """Freeze the procedural Line Art into stored strokes + mute the modifier so it
    stops re-tracing on every eval / export / render. Done via the data API (no
    bpy.ops) so it's reliable in the live session's timer context. Returns True if
    baked (or already baked); never fatal - on failure the modifier is left live.
    Baked radii get the near-camera screen-width clamp (clamp_screen_width)."""
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None:
        return False
    m = _lineart_mod(gp)
    if m is None:
        return False
    if not m.show_viewport:
        return True                       # already baked (guards against dupes)
    try:
        bpy.context.view_layer.update()   # ensure the live modifier has traced
        dg = bpy.context.evaluated_depsgraph_get()
        ev = gp.evaluated_get(dg)
        for li, slay in enumerate(ev.data.layers):
            if li >= len(gp.data.layers):
                continue
            dlay = gp.data.layers[li]
            if not len(slay.frames) or not len(dlay.frames):
                continue
            _copy_drawing(slay.frames[0].drawing, dlay.frames[0].drawing)
    except Exception as ex:
        print("Blendit: bake_line_art failed: %s" % ex)
        return False
    m.show_viewport = False
    m.show_render = False
    clamp_screen_width()
    return True


def unbake_line_art():
    """Drop the baked strokes and re-enable the modifier so the next eval retraces."""
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None:
        return
    m = _lineart_mod(gp)
    if m is None:
        return
    try:
        for lay in gp.data.layers:
            for fr in lay.frames:
                drw = fr.drawing
                if len(drw.strokes):
                    drw.remove_strokes(indices=list(range(len(drw.strokes))))
    except Exception:
        pass
    m.show_viewport = True
    m.show_render = True


def set_sketchiness(amount):
    """Wobble the lines for a hand-drawn look (0 = clean)."""
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None:
        return
    nz = _noise_mod(gp)
    if amount <= 0.0:
        if nz is not None:
            try:
                gp.modifiers.remove(nz)
            except Exception:
                pass
        return
    if nz is None:
        try:
            nz = gp.modifiers.new("Sketch", "GREASE_PENCIL_NOISE")
        except Exception:
            return
    # Position wobble only (hand-drawn), not thickness/opacity variation.
    if hasattr(nz, "factor"):
        nz.factor = float(amount)
    for attr in ("factor_thickness", "factor_strength", "factor_uvs"):
        if hasattr(nz, attr):
            try:
                setattr(nz, attr, 0.0)
            except Exception:
                pass
    if hasattr(nz, "noise_scale"):
        try:
            nz.noise_scale = 0.4
        except Exception:
            pass


def set_line_overshoot(amount):
    """Extend every stroke past its endpoints by ~`amount` metres - the
    hand-drawn habit of overdrawing lines through corners (the classic
    architectural-sketch tell). Randomised per stroke so no two corners
    overshoot identically; straight extensions (curvature off) like a ruler
    stroke that didn't stop in time. 0 removes the modifier."""
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None:
        return
    ln = _length_mod(gp)
    if amount <= 0.0:
        if ln is not None:
            try:
                gp.modifiers.remove(ln)
            except Exception:
                pass
        return
    if ln is None:
        try:
            ln = gp.modifiers.new("Overshoot", "GREASE_PENCIL_LENGTH")
        except Exception:
            return
    for attr, val in (("mode", "ABSOLUTE"),
                      ("use_curvature", False),
                      ("start_length", float(amount)),
                      ("end_length", float(amount)),
                      ("use_random", True),
                      ("random_start_factor", float(amount) * 0.7),
                      ("random_end_factor", float(amount) * 0.7),
                      ("seed", 7)):
        try:
            setattr(ln, attr, val)
        except Exception:
            pass


def get_line_overshoot():
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is not None:
        ln = _length_mod(gp)
        if ln is not None:
            try:
                return float(ln.start_length)
            except Exception:
                return None
    return None


# --- toon (cel) shading -----------------------------------------------------
def _set_ramp_shades(ramp, base, shades):
    shades = max(2, min(6, int(shades)))
    ramp.interpolation = "CONSTANT"
    els = ramp.elements
    while len(els) > 1:
        els.remove(els[-1])
    # brightness for each band, darkest (shadow) -> full (lit)
    for i in range(shades):
        pos = i / float(shades)
        # Lighter shadow floor so the anime bands read bright, not near-black.
        bright = 0.6 + 0.4 * (i / float(shades - 1))
        col = (base[0] * bright, base[1] * bright, base[2] * bright, 1.0)
        if i == 0:
            els[0].position = 0.0
            els[0].color = col
        else:
            e = els.new(pos)
            e.color = col


def _toon_material(rec, shades):
    raw = rec.get("base_color", [0.8, 0.8, 0.8])
    # Anime palettes are bright + saturated; real Revit albedos (e.g. steel 0.21)
    # are dark. Lift them (gamma) so the toon bands read vibrant, not near-black.
    base = [min(1.0, max(0.0, float(c)) ** 0.45) for c in raw]
    mat = bpy.data.materials.new("Toon_" + (rec.get("name") or rec.get("id") or "m"))
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-300, 0)
    diff.inputs["Color"].default_value = (base[0], base[1], base[2], 1.0)
    s2rgb = nt.nodes.new("ShaderNodeShaderToRGB")
    s2rgb.location = (-100, 0)
    nt.links.new(diff.outputs["BSDF"], s2rgb.inputs["Shader"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (120, 0)
    _set_ramp_shades(ramp.color_ramp, base, shades)
    nt.links.new(s2rgb.outputs["Color"], ramp.inputs["Fac"])
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.location = (400, 0)
    nt.links.new(ramp.outputs["Color"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def apply_toon(loaded, shades=3):
    by_id = {rec["id"]: _toon_material(rec, shades)
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


def set_toon_shades(loaded, shades):
    """Live update: rebuild the toon ramps with a new band count."""
    apply_toon(loaded, shades)


# --- shadow hatch (tone-driven CONTINUOUS hatch lines) ---------------------
# Extract the surface shading (Shader-to-RGB, includes cast shadows) and use it to
# set the WIDTH of a single continuous screen-space stripe pattern via a stepped
# ramp: lit = blank paper, light shade = thin lines, deeper shadow = thicker lines
# that merge toward solid black. Because tone only sets line THICKNESS (never turns
# a line on/off per pixel), the lines stay continuous - no start/stop dashing - and
# the stepped ramp gives several distinct tones. Screen-space (Window) coords keep
# the hatch a constant width regardless of distance/angle (reads as hand-drawn ink,
# not a texture stuck to the wall). EEVEE-only (Shader-to-RGB).
#
# `bands`: (lit_threshold, line_width) stops, darkest first; CONSTANT-interpolated.
_HATCH_BANDS = [(0.0, 1.0), (0.16, 0.55), (0.36, 0.32), (0.56, 0.15), (0.76, 0.0)]


def make_hatch_material(name="BIR_Hatch", density=10.0, cross=False,
                        bands=None, ao_distance=0.0, weight=1.0, cross_dark=0.45,
                        angle=0.0, cross_angle=90.0):
    import math
    bands = bands or _HATCH_BANDS
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1200, 0)

    # 1. shaded tone (0 = shadow .. 1 = lit), cast shadows included
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-1040, -280)
    diff.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)
    s2 = nt.nodes.new("ShaderNodeShaderToRGB")
    s2.location = (-840, -280)
    nt.links.new(diff.outputs["BSDF"], s2.inputs["Shader"])
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    bw.location = (-660, -280)
    nt.links.new(s2.outputs["Color"], bw.inputs["Color"])
    tone = bw.outputs["Val"]

    # Darken occluded crevices (box-ground contact, gaps) so deep pockets fall into
    # the dense bands - the near-solid base shadows in a hand drawing.
    if ao_distance and ao_distance > 0.0:
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
        ao.location = (-840, -480)
        try:
            ao.inputs["Distance"].default_value = float(ao_distance)
        except Exception:
            pass
        mul_ao = nt.nodes.new("ShaderNodeMath")
        mul_ao.location = (-600, -360)
        mul_ao.operation = "MULTIPLY"
        nt.links.new(tone, mul_ao.inputs[0])
        nt.links.new(ao.outputs["AO"], mul_ao.inputs[1])
        tone = mul_ao.outputs["Value"]

    # 2. tone -> line WIDTH, stepped (CONSTANT = hard tone bands). `weight` scales
    # every band width, so the user can dial the lines thinner/thicker globally.
    def _w(val):
        return max(0.0, min(1.0, val * weight))
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-480, -280)
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    els = cr.elements
    els[0].position, els[0].color = bands[0][0], (_w(bands[0][1]),) * 3 + (1.0,)
    els[1].position, els[1].color = bands[1][0], (_w(bands[1][1]),) * 3 + (1.0,)
    for pos, val in bands[2:]:
        e = els.new(pos)
        e.color = (_w(val),) * 3 + (1.0,)
    nt.links.new(tone, ramp.inputs["Fac"])
    wbw = nt.nodes.new("ShaderNodeRGBToBW")
    wbw.location = (-280, -280)
    nt.links.new(ramp.outputs["Color"], wbw.inputs["Color"])
    width = wbw.outputs["Val"]

    # Phase 1 - SURFACE-ATTACHED strokes (triplanar world-space): the hatch lies in
    # each surface's own plane, so vertical walls get verticals, floors / roofs /
    # ground get in-plane strokes, and it all stays perspective-correct (the strokes
    # live ON the surface). Phase 2 - a perpendicular CROSS-HATCH pass that NESTS in:
    # it only switches on below `cross_dark` tone (like adding strokes in a darker
    # TAM tier), so cross-hatch appears only in the shadows.
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-1060, 520)
    pos = nt.nodes.new("ShaderNodeSeparateXYZ")
    pos.location = (-880, 600)
    nt.links.new(geo.outputs["Position"], pos.inputs["Vector"])
    nrm = nt.nodes.new("ShaderNodeSeparateXYZ")
    nrm.location = (-880, 400)
    nt.links.new(geo.outputs["Normal"], nrm.inputs["Vector"])
    px, py, pz = pos.outputs["X"], pos.outputs["Y"], pos.outputs["Z"]

    def _m(op, a, b=None, loc=(0, 0)):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        n.location = loc
        for idx, v in ((0, a), (1, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[idx].default_value = float(v)
            else:
                nt.links.new(v, n.inputs[idx])
        return n.outputs["Value"]

    # triplanar blend weights = |normal|^4 (sharpened so the dominant face wins),
    # normalized so they sum to 1.
    def _wt(comp, y):
        return _m("POWER", _m("ABSOLUTE", comp, None, (-720, y)), 4.0, (-580, y))
    wx = _wt(nrm.outputs["X"], 520)
    wy = _wt(nrm.outputs["Y"], 440)
    wz = _wt(nrm.outputs["Z"], 360)
    wsum = _m("ADD", _m("ADD", wx, wy, (-440, 480)), wz, (-320, 470))
    wxn = _m("DIVIDE", wx, wsum, (-180, 540))
    wyn = _m("DIVIDE", wy, wsum, (-180, 460))
    wzn = _m("DIVIDE", wz, wsum, (-180, 380))

    def _stripe(coord, w, y):
        return _m("LESS_THAN",
                  _m("FRACT", _m("MULTIPLY", coord, density, (40, y)),
                     None, (180, y)),
                  w, (320, y))

    # ROTATE the stripe direction WITHIN each surface plane: the stripe coordinate is
    # a unit combination of that plane's two in-plane axes, u*cos + v*sin. cos/sin are
    # baked in at build time (the angle slider rebuilds the material), and since
    # (cos,sin) is a unit vector the line spacing (density) stays the same at any
    # angle. angle 0 = the original "vertical" set; the cross set has its own angle
    # (default +90 = perpendicular, but any crosshatch angle is allowed).
    def _rot(u, v, c, s, y):
        if abs(s) < 1e-6:
            return u                                   # 0 / 180 deg -> in-plane axis u
        if abs(c) < 1e-6:
            return v                                   # 90 / 270 deg -> axis v
        return _m("ADD", _m("MULTIPLY", u, c, (-60, y)),
                  _m("MULTIPLY", v, s, (-60, y - 40)), (100, y))

    # (u, v) in-plane axes per normal plane: X-face = YZ, Y-face = XZ, Z-face = XY.
    _planes = ((py, pz), (px, pz), (px, py))

    def _triplanar(cos_a, sin_a, w, y0):
        sx = _rot(_planes[0][0], _planes[0][1], cos_a, sin_a, y0)
        sy = _rot(_planes[1][0], _planes[1][1], cos_a, sin_a, y0 - 80)
        sz = _rot(_planes[2][0], _planes[2][1], cos_a, sin_a, y0 - 160)
        a = _m("MULTIPLY", _stripe(sx, w, y0), wxn, (480, y0))
        b = _m("MULTIPLY", _stripe(sy, w, y0 - 80), wyn, (480, y0 - 80))
        c = _m("MULTIPLY", _stripe(sz, w, y0 - 160), wzn, (480, y0 - 160))
        return _m("ADD", _m("ADD", a, b, (640, y0 - 40)), c, (780, y0 - 80))

    ch, sh = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    primary = _triplanar(ch, sh, width, 760)
    cover = primary
    if cross:
        cc, sc = math.cos(math.radians(cross_angle)), math.sin(math.radians(cross_angle))
        cgate = _m("LESS_THAN", tone, cross_dark, (40, 200))   # 1 in the shadows
        cwidth = _m("MULTIPLY", width, cgate, (220, 220))
        crossm = _triplanar(cc, sc, cwidth, 260)               # rotated cross set
        cover = _m("MAXIMUM", primary, crossm, (940, 500))

    inv = nt.nodes.new("ShaderNodeMath")         # ink value = 1 - coverage
    inv.location = (1060, 320)
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(cover, inv.inputs[1])

    emi = nt.nodes.new("ShaderNodeEmission")
    emi.location = (380, 120)
    nt.links.new(inv.outputs["Value"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def apply_hatch(loaded, density=10.0, cross=False, weight=1.0,
                angle=0.0, cross_angle=90.0):
    """Assign ONE shared shadow-hatch material to every mesh (and the ground, so cast
    shadows hatch). The material reads each surface's own shading, so one instance
    drives the whole scene. Returns the material."""
    mat = make_hatch_material(density=density, cross=cross, weight=weight,
                              angle=angle, cross_angle=cross_angle)
    for node, obj in loaded.node_to_object.items():
        if getattr(obj, "type", None) == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(mat)
    g = _ground()
    if g is not None:
        g.data.materials.clear()
        g.data.materials.append(mat)
    return mat


def set_hatch(loaded, density, cross, weight=1.0, angle=0.0, cross_angle=90.0):
    """Live update: rebuild + reassign the hatch material with new params."""
    apply_hatch(loaded, density=float(density), cross=bool(cross),
                weight=float(weight), angle=float(angle),
                cross_angle=float(cross_angle))


# --- depth-cued line weight (tiered, survives vector export) ----------------
# Classic drafting: near edges thick + dark, far edges thin + pale. A continuous
# fade can't survive SVG/PDF (one colour + opacity per path), so we TIER it: each
# depth band is a uniform GP material (grey) + uniform width, which exports cleanly
# (one flat colour + width per path) AND is the authentic drafting convention.
# Operates on the BAKED strokes (call after bake_line_art).
def _ensure_tier_material(gp, i, col):
    name = "BIR_Tier%d" % i
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        bpy.data.materials.create_gpencil_data(mat)
    if mat.grease_pencil is not None:
        mat.grease_pencil.color = (col[0], col[1], col[2], 1.0)
    for j, m in enumerate(gp.data.materials):
        if m == mat:
            return j
    gp.data.materials.append(mat)
    return len(gp.data.materials) - 1


def apply_depth_cue(near_radius=0.03, far_radius=0.008, tiers=4, far_gray=0.6):
    """Tier the baked Line Art by camera distance: near strokes thick + the line
    colour, far strokes thin + faded toward grey. Returns True if applied. Requires
    a baked Line Art (no-op otherwise)."""
    gp = bpy.data.objects.get(_GP_NAME)
    if gp is None or not is_line_art_baked():
        return False
    cam = bpy.context.scene.camera
    if cam is None:
        return False
    import mathutils
    cam_loc = cam.matrix_world.translation
    mw = gp.matrix_world

    strokes = [s for lay in gp.data.layers for fr in lay.frames
               for s in fr.drawing.strokes]
    if not strokes:
        return False

    def _depth(s):
        pts = s.points
        if not len(pts):
            return 0.0
        acc = mathutils.Vector((0.0, 0.0, 0.0))
        for p in pts:
            acc = acc + (mw @ p.position)
        return ((acc / len(pts)) - cam_loc).length

    depths = [_depth(s) for s in strokes]
    dmin, dmax = min(depths), max(depths)
    span = (dmax - dmin) or 1.0

    base = get_line_art_color() or (0.0, 0.0, 0.0)
    tiers = max(2, int(tiers))
    tier_idx = []
    for i in range(tiers):
        t = i / float(tiers - 1)
        col = tuple(base[k] * (1.0 - t) + far_gray * t for k in range(3))
        tier_idx.append(_ensure_tier_material(gp, i, col))

    for s, d in zip(strokes, depths):
        t = (d - dmin) / span                     # 0 near .. 1 far
        tier = min(tiers - 1, int(t * tiers))
        s.material_index = tier_idx[tier]
        r = max(0.0005, near_radius * (1.0 - t) + far_radius * t)
        for p in s.points:
            p.radius = r
    for lay in gp.data.layers:
        for fr in lay.frames:
            try:
                fr.drawing.tag_positions_changed()
            except Exception:
                pass
    return True
