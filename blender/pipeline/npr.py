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
    """Line thickness scaled to the model so it reads at any project size."""
    try:
        from .camera import _scene_bbox
        bb = _scene_bbox()
        if bb:
            mn, mx = bb
            diag = (mx - mn).length
            return max(0.004, diag * 0.0004)
    except Exception:
        pass
    return 0.02


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
    Line Art is camera-relative, so callers snap the camera to the view first."""
    m = _active_lineart_mod()
    if m is not None:
        try:                       # nudge a clean recompute on the next eval
            m.show_viewport = False
            m.show_viewport = True
        except Exception:
            pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


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
