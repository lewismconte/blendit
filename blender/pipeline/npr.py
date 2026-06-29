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


def _set_line_color(gp, color):
    for mat in gp.data.materials:
        if mat is not None and mat.grease_pencil is not None:
            mat.grease_pencil.color = (color[0], color[1], color[2], 1.0)
            return
    mat = bpy.data.materials.new(_LINE_MAT)
    bpy.data.materials.create_gpencil_data(mat)
    mat.grease_pencil.color = (color[0], color[1], color[2], 1.0)
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


def bake_line_art():
    """Freeze the procedural Line Art into stored strokes + mute the modifier so it
    stops re-tracing on every eval / export / render. Done via the data API (no
    bpy.ops) so it's reliable in the live session's timer context. Returns True if
    baked (or already baked); never fatal - on failure the modifier is left live."""
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


def make_hatch_material(name="BIR_Hatch", density=42.0, cross=False,
                        bands=None, ao_distance=0.0):
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

    # 2. tone -> line WIDTH, stepped (CONSTANT = hard tone bands)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-480, -280)
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    els = cr.elements
    els[0].position, els[0].color = bands[0][0], (bands[0][1],) * 3 + (1.0,)
    els[1].position, els[1].color = bands[1][0], (bands[1][1],) * 3 + (1.0,)
    for pos, val in bands[2:]:
        e = els.new(pos)
        e.color = (val, val, val, 1.0)
    nt.links.new(tone, ramp.inputs["Fac"])
    wbw = nt.nodes.new("ShaderNodeRGBToBW")
    wbw.location = (-280, -280)
    nt.links.new(ramp.outputs["Color"], wbw.inputs["Color"])
    width = wbw.outputs["Val"]

    # Flat screen-space stripes converge WRONG under perspective (dead-parallel).
    # Build the hatch in the VIEW-RAY ANGULAR domain instead - like a striped
    # environment wrapped on the view sphere: stripes of constant azimuth around
    # world-up are vertical lines that converge to the zenith / nadir vanishing
    # points (true perspective). Cross-hatch uses the elevation angle (the
    # concentric latitude lines).
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-1040, 400)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-860, 400)
    nt.links.new(geo.outputs["Incoming"], sep.inputs["Vector"])
    sx, sy, sz = sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"]

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

    def _coverage(angle, y):
        phase = _m("MULTIPLY", angle, density, (-520, y))
        saw = _m("FRACT", phase, None, (-360, y))
        return _m("LESS_THAN", saw, width, (-200, y))     # tone sets line thickness

    azimuth = _m("ARCTAN2", sx, sy, (-680, 380))           # around world-up (Z)
    cover = _coverage(azimuth, 380)
    if cross:                                              # concentric latitude lines
        hyp = _m("SQRT", _m("ADD", _m("MULTIPLY", sx, sx, (-760, 600)),
                            _m("MULTIPLY", sy, sy, (-760, 520)), (-600, 560)),
                 None, (-440, 560))
        elevation = _m("ARCTAN2", sz, hyp, (-280, 560))
        cover = _m("MAXIMUM", cover, _coverage(elevation, 560), (40, 470))

    inv = nt.nodes.new("ShaderNodeMath")         # ink value = 1 - coverage
    inv.location = (220, 320)
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(cover, inv.inputs[1])

    emi = nt.nodes.new("ShaderNodeEmission")
    emi.location = (380, 120)
    nt.links.new(inv.outputs["Value"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def apply_hatch(loaded, density=42.0, cross=False):
    """Assign ONE shared shadow-hatch material to every mesh (and the ground, so cast
    shadows hatch). The material reads each surface's own shading, so one instance
    drives the whole scene. Returns the material."""
    mat = make_hatch_material(density=density, cross=cross)
    for node, obj in loaded.node_to_object.items():
        if getattr(obj, "type", None) == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(mat)
    g = _ground()
    if g is not None:
        g.data.materials.clear()
        g.data.materials.append(mat)
    return mat


def set_hatch(loaded, density, cross):
    """Live update: rebuild + reassign the hatch material with new params."""
    apply_hatch(loaded, density=float(density), cross=bool(cross))


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
