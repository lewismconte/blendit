"""Curated procedural material library (Blender side).

Revit can't hand us textures cleanly: the appearance-asset bitmaps are awkward to
read in IronPython, and the tessellated geometry carries NO UVs to map them onto
(Revit textures procedurally at render time via real-world scale). So instead of
round-tripping images + UV channels, we keep a small set of *procedural* surfaces
built from Blender's native texture nodes and match them to the Revit material by
name. This is the "curated library" path: zero binary assets, no licensing, tiles
infinitely, and - the key trick - it needs no UVs, because every surface is driven
by **Object** coordinates (real-world metres), so a brick is ~215 mm regardless of
the mesh.

The Revit base_color is carried through as the dominant tint, so a "Brick, Red"
stays red and a "Concrete, Precast" stays grey - we add surface detail, we don't
discard Revit's colour intent.

When the contract later carries an explicit `base_color_texture` (the Revit
appearance-asset extraction path), build_material uses that directly; this module
is the fallback/default source. Same Blender node graph either way.
"""
import bpy


def _clamp(v):
    return max(0.0, min(1.0, v))


def _shade(rgb, f):
    """A tint variant: the base colour scaled by `f` (clamped, opaque)."""
    return (_clamp(rgb[0] * f), _clamp(rgb[1] * f), _clamp(rgb[2] * f), 1.0)


def _proj(nt, size_m):
    """TexCoord(Object) -> Mapping scaled so 1 texture unit == `size_m` metres.

    Object coords are the merged mesh's local space; merge bakes matrix_world into
    the vertices with the object at the origin, so Object == world metres -> the
    pattern is real-world sized and consistent across the whole merged surface."""
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-1000, -200)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-800, -200)
    s = 1.0 / max(1e-4, float(size_m))
    mp.inputs["Scale"].default_value = (s, s, s)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def _bump(nt, bsdf, height_socket, strength, distance=0.01):
    b = nt.nodes.new("ShaderNodeBump")
    b.location = (200, -300)
    b.inputs["Strength"].default_value = float(strength)
    b.inputs["Distance"].default_value = float(distance)
    nt.links.new(height_socket, b.inputs["Height"])
    nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])


def _ramp(nt, fac_socket, lo_color, hi_color):
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.location = (0, 100)
    r.color_ramp.elements[0].color = lo_color
    r.color_ramp.elements[1].color = hi_color
    nt.links.new(fac_socket, r.inputs["Fac"])
    return r.outputs["Color"]


# --- surface builders: (nt, bsdf, tint_rgb, roughness) ----------------------
def _triplanar_color(nt, build2d):
    """Project a 2-D pattern onto the three world planes and blend by the face
    normal, so coursed/gridded surfaces (brick, tile, planks, roof courses)
    read correctly on floors AND on walls facing any direction - no UVs, no
    images. `build2d(vec_socket, loc)` must return a COLOR output socket.
    Returns (blended_color_socket, world_mapping_vector) - the vector is for
    callers' 3-D bump noise."""
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-1100, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-950, 0)
    mp.inputs["Scale"].default_value = (1.0, 1.0, 1.0)  # 1 unit == 1 metre
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-800, 0)
    nt.links.new(mp.outputs["Vector"], sep.inputs["Vector"])

    def _combine(a, b, y):
        c = nt.nodes.new("ShaderNodeCombineXYZ")
        c.location = (-650, y)
        nt.links.new(a, c.inputs["X"])
        nt.links.new(b, c.inputs["Y"])
        return c.outputs["Vector"]

    vz = _combine(sep.outputs["X"], sep.outputs["Y"], 300)   # floor  (normal ~ Z)
    vy = _combine(sep.outputs["X"], sep.outputs["Z"], 0)     # wall facing Y
    vx = _combine(sep.outputs["Y"], sep.outputs["Z"], -300)  # wall facing X
    cz = build2d(vz, (-450, 300))
    cy = build2d(vy, (-450, 0))
    cx = build2d(vx, (-450, -300))

    # blend weights = normalized |true normal|
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-800, -500)
    sn = nt.nodes.new("ShaderNodeSeparateXYZ")
    sn.location = (-650, -500)
    nt.links.new(geo.outputs["True Normal"], sn.inputs["Vector"])

    def _math(op, a, b=None, y=0):
        m = nt.nodes.new("ShaderNodeMath")
        m.operation = op
        m.location = (-450, y)
        nt.links.new(a, m.inputs[0])
        if b is not None:
            nt.links.new(b, m.inputs[1])
        return m.outputs["Value"]

    ax = _math("ABSOLUTE", sn.outputs["X"], y=-450)
    ay = _math("ABSOLUTE", sn.outputs["Y"], y=-520)
    az = _math("ABSOLUTE", sn.outputs["Z"], y=-590)
    summ = _math("ADD", _math("ADD", ax, ay, y=-660), az, y=-700)
    wx = _math("DIVIDE", ax, summ, y=-450)
    wy = _math("DIVIDE", ay, summ, y=-520)
    wz = _math("DIVIDE", az, summ, y=-590)

    def _scale_col(color, w, y):
        m = nt.nodes.new("ShaderNodeVectorMath")
        m.operation = "SCALE"
        m.location = (-200, y)
        nt.links.new(color, m.inputs[0])
        nt.links.new(w, m.inputs["Scale"])
        return m.outputs["Vector"]

    def _vadd(a, b, y):
        m = nt.nodes.new("ShaderNodeVectorMath")
        m.operation = "ADD"
        m.location = (0, y)
        nt.links.new(a, m.inputs[0])
        nt.links.new(b, m.inputs[1])
        return m.outputs["Vector"]

    blended = _vadd(_vadd(_scale_col(cx, wx, -300),
                          _scale_col(cy, wy, 0), -150),
                    _scale_col(cz, wz, 300), 0)
    return blended, mp.outputs["Vector"]


def _weathered(nt, col, vec, lo=0.86, hi=1.08, scale=0.4):
    """Multiply metre-scale weathering/variation patches onto a colour socket
    (real walls are never one uniform tone). Returns the new socket; falls
    back to the input untouched on older Mix-node APIs."""
    try:
        big = nt.nodes.new("ShaderNodeTexNoise")
        big.location = (-450, 620)
        big.inputs["Scale"].default_value = float(scale)
        big.inputs["Detail"].default_value = 2.0
        nt.links.new(vec, big.inputs["Vector"])
        mot = _ramp(nt, big.outputs["Fac"], _shade([1, 1, 1], lo),
                    _shade([1, 1, 1], hi))
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (150, 320)
        mix.inputs[0].default_value = 1.0          # Factor
        nt.links.new(col, mix.inputs[6])           # A (color)
        nt.links.new(mot, mix.inputs[7])           # B (color)
        return mix.outputs[2]                      # Result (color)
    except Exception:
        return col


def _brick_node(nt, tint, vec, loc, width=0.215, height=0.065, mortar=0.006,
                mortar_col=(0.55, 0.53, 0.50, 1.0), offset=0.5, shade2=0.72):
    """One Brick texture (the 2-D coursing pattern) fed a metre-scaled vector."""
    b = nt.nodes.new("ShaderNodeTexBrick")
    b.location = loc
    b.inputs["Scale"].default_value = 1.0
    b.inputs["Brick Width"].default_value = float(width)
    b.inputs["Row Height"].default_value = float(height)
    b.inputs["Mortar Size"].default_value = float(mortar)
    b.inputs["Mortar Smooth"].default_value = 0.1
    b.inputs["Color1"].default_value = _shade(tint, 1.0)
    b.inputs["Color2"].default_value = _shade(tint, shade2)
    b.inputs["Mortar"].default_value = mortar_col
    b.offset = float(offset)
    b.offset_frequency = 2
    nt.links.new(vec, b.inputs["Vector"])
    return b


def _brick(nt, bsdf, tint, roughness):
    """Brick coursing, triplanar. Light mortar (real mortar is pale - the old
    near-black joints read as cartoon brick) + metre-scale weathering patches."""
    col, vec = _triplanar_color(
        nt, lambda v, loc: _brick_node(nt, tint, v, loc).outputs["Color"])
    col = _weathered(nt, col, vec, 0.82, 1.06)
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.85)
    # subtle orientation-independent relief (3-D noise, so no projection issue)
    nb = nt.nodes.new("ShaderNodeTexNoise")
    nb.location = (-450, 500)
    nb.inputs["Scale"].default_value = 40.0
    nt.links.new(vec, nb.inputs["Vector"])
    _bump(nt, bsdf, nb.outputs["Fac"], 0.12)


def _tile(nt, bsdf, tint, roughness):
    """Glazed ceramic tile: a square grout grid (brick node, zero offset),
    slight tile-to-tile shade variation, smooth glossy finish."""
    col, vec = _triplanar_color(
        nt, lambda v, loc: _brick_node(
            nt, tint, v, loc, width=0.3, height=0.3, mortar=0.004,
            mortar_col=(0.62, 0.61, 0.58, 1.0), offset=0.0,
            shade2=0.93).outputs["Color"])
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = min(max(roughness, 0.15), 0.3)
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.location = (-450, 500)
    fine.inputs["Scale"].default_value = 25.0
    nt.links.new(vec, fine.inputs["Vector"])
    _bump(nt, bsdf, fine.outputs["Fac"], 0.03, distance=0.003)


def _roof_tile(nt, bsdf, tint, roughness):
    """Roof tiles: offset courses (colour) + horizontal course relief. The bump
    is a world-Z banded wave, so courses stay horizontal on any roof slope."""
    col, vec = _triplanar_color(
        nt, lambda v, loc: _brick_node(
            nt, tint, v, loc, width=0.32, height=0.34, mortar=0.014,
            mortar_col=(0.06, 0.05, 0.05, 1.0), shade2=0.8).outputs["Color"])
    col = _weathered(nt, col, vec, 0.8, 1.08)
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.75)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.location = (-450, 500)
    wave.wave_type = "BANDS"
    wave.bands_direction = "Z"
    wave.inputs["Scale"].default_value = 2.2       # ~0.34 m course pitch
    nt.links.new(vec, wave.inputs["Vector"])
    _bump(nt, bsdf, wave.outputs["Fac"], 0.35, distance=0.012)


def _planks(nt, bsdf, tint, roughness):
    """Wood planks / decking / floorboards: staggered board seams with
    board-to-board shade variation, wood grain running through, satin finish."""
    col, vec = _triplanar_color(
        nt, lambda v, loc: _brick_node(
            nt, tint, v, loc, width=2.4, height=0.135, mortar=0.005,
            mortar_col=(0.04, 0.03, 0.02, 1.0), shade2=0.8).outputs["Color"])
    # grain over the boards
    try:
        wave = nt.nodes.new("ShaderNodeTexWave")
        wave.location = (-450, 620)
        wave.wave_type = "BANDS"
        wave.bands_direction = "X"
        wave.inputs["Scale"].default_value = 2.0
        wave.inputs["Distortion"].default_value = 9.0
        wave.inputs["Detail"].default_value = 2.0
        nt.links.new(vec, wave.inputs["Vector"])
        grain = _ramp(nt, wave.outputs["Fac"], _shade([1, 1, 1], 0.86),
                      _shade([1, 1, 1], 1.06))
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (150, 320)
        mix.inputs[0].default_value = 1.0
        nt.links.new(col, mix.inputs[6])
        nt.links.new(grain, mix.inputs[7])
        col = mix.outputs[2]
        _bump(nt, bsdf, wave.outputs["Fac"], 0.08, distance=0.004)
    except Exception:
        pass
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = min(max(roughness, 0.3), 0.5)


def _corrugated(nt, bsdf, tint, roughness):
    """Corrugated / profiled metal sheeting (Colorbond and friends): metal with
    a sine rib relief. Two wave directions blended by usage keeps ribs present
    on walls facing any way (one wave alone goes flat on its own axis)."""
    bsdf.inputs["Base Color"].default_value = _shade(tint, 1.0)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = min(max(roughness, 0.3), 0.5)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-800, -300)
    wx = nt.nodes.new("ShaderNodeTexWave")
    wx.location = (-600, -250)
    wx.wave_type = "BANDS"
    wx.bands_direction = "X"
    wx.inputs["Scale"].default_value = 82.0        # ~76 mm rib pitch (2*pi/scale)
    nt.links.new(tc.outputs["Object"], wx.inputs["Vector"])
    wy = nt.nodes.new("ShaderNodeTexWave")
    wy.location = (-600, -450)
    wy.wave_type = "BANDS"
    wy.bands_direction = "Y"
    wy.inputs["Scale"].default_value = 82.0
    nt.links.new(tc.outputs["Object"], wy.inputs["Vector"])
    # AVERAGE the two directions (a MAXIMUM saturates whenever the off-axis
    # wave sits high at that world position, flattening the ribs entirely);
    # each face keeps ~half-amplitude ribs, so the bump strength compensates.
    mx = nt.nodes.new("ShaderNodeMath")
    mx.operation = "ADD"
    mx.location = (-400, -350)
    nt.links.new(wx.outputs["Fac"], mx.inputs[0])
    nt.links.new(wy.outputs["Fac"], mx.inputs[1])
    half = nt.nodes.new("ShaderNodeMath")
    half.operation = "MULTIPLY"
    half.location = (-250, -350)
    half.inputs[1].default_value = 0.5
    nt.links.new(mx.outputs["Value"], half.inputs[0])
    _bump(nt, bsdf, half.outputs["Value"], 1.0, distance=0.015)


def _gravel(nt, bsdf, tint, roughness):
    """Loose gravel: voronoi stones, chunky relief, bone dry."""
    vec = _proj(nt, 1.0)
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.location = (-400, 0)
    vor.inputs["Scale"].default_value = 55.0
    nt.links.new(vec, vor.inputs["Vector"])
    col = _ramp(nt, vor.outputs["Distance"], _shade(tint, 1.15),
                _shade(tint, 0.6))
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.95)
    _bump(nt, bsdf, vor.outputs["Distance"], 0.45, distance=0.012)


def _wood(nt, bsdf, tint, roughness):
    vec = _proj(nt, 1.0)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.location = (-400, 0)
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = 1.4
    wave.inputs["Distortion"].default_value = 12.0     # grain rings
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(vec, wave.inputs["Vector"])
    col = _ramp(nt, wave.outputs["Fac"], _shade(tint, 0.6), _shade(tint, 1.0))
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.45)
    _bump(nt, bsdf, wave.outputs["Fac"], 0.15)


def _concrete(nt, bsdf, tint, roughness):
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, 0)
    n.inputs["Scale"].default_value = 6.0
    n.inputs["Detail"].default_value = 6.0
    n.inputs["Roughness"].default_value = 0.6
    nt.links.new(vec, n.inputs["Vector"])
    col = _ramp(nt, n.outputs["Fac"], _shade(tint, 0.82), _shade(tint, 1.08))
    # Large-scale mottling on top of the fine grain: real concrete reads by its
    # metre-scale pour/weathering variation, not just the surface noise.
    try:
        big = nt.nodes.new("ShaderNodeTexNoise")
        big.location = (-400, 300)
        big.inputs["Scale"].default_value = 0.45
        big.inputs["Detail"].default_value = 2.0
        nt.links.new(vec, big.inputs["Vector"])
        mot = _ramp(nt, big.outputs["Fac"], _shade([1, 1, 1], 0.90),
                    _shade([1, 1, 1], 1.06))
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (150, 150)
        mix.inputs[0].default_value = 1.0          # Factor
        nt.links.new(col, mix.inputs[6])           # A (color)
        nt.links.new(mot, mix.inputs[7])           # B (color)
        col = mix.outputs[2]                       # Result (color)
    except Exception:
        pass                                       # older Mix node API: skip mottle
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.8)
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.location = (-400, -300)
    fine.inputs["Scale"].default_value = 35.0
    nt.links.new(vec, fine.inputs["Vector"])
    _bump(nt, bsdf, fine.outputs["Fac"], 0.1)


def _plaster(nt, bsdf, tint, roughness):
    """Smooth painted / rendered wall finish: the flat colour with only a
    faint fine grain. Plaster reads by its SMOOTHNESS - the old stone/marble
    veining it used to get was exactly wrong."""
    bsdf.inputs["Base Color"].default_value = _shade(tint, 1.0)
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.55)
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, -300)
    n.inputs["Scale"].default_value = 90.0
    n.inputs["Detail"].default_value = 2.0
    nt.links.new(vec, n.inputs["Vector"])
    _bump(nt, bsdf, n.outputs["Fac"], 0.04, distance=0.004)


def _asphalt(nt, bsdf, tint, roughness):
    """Dark rough paving: fine aggregate speckle, very matte. Stays DARK
    whatever the Revit colour says - light asphalt reads as concrete."""
    m = max(tint) if max(tint) > 0 else 1.0
    dark = [c * min(1.0, 0.14 / m) for c in tint]   # clamp brightness, keep hue
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, 0)
    n.inputs["Scale"].default_value = 300.0          # aggregate speckle
    n.inputs["Detail"].default_value = 3.0
    nt.links.new(vec, n.inputs["Vector"])
    col = _ramp(nt, n.outputs["Fac"], _shade(dark, 0.7), _shade(dark, 1.35))
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.92)
    _bump(nt, bsdf, n.outputs["Fac"], 0.15, distance=0.003)


def _water(nt, bsdf, tint, roughness):
    """Water: physical transmission + a rippled surface normal. Full effect
    in Cycles; EEVEE shows a glossy rippled surface (no per-material
    refraction flags on this opaque-record path)."""
    bsdf.inputs["Base Color"].default_value = _shade(tint, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["IOR"].default_value = 1.33
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.9
    vec = _proj(nt, 1.0)
    ripple = nt.nodes.new("ShaderNodeTexNoise")
    ripple.location = (-400, -300)
    ripple.inputs["Scale"].default_value = 5.0
    ripple.inputs["Detail"].default_value = 4.0
    ripple.inputs["Distortion"].default_value = 0.4
    nt.links.new(vec, ripple.inputs["Vector"])
    _bump(nt, bsdf, ripple.outputs["Fac"], 0.3, distance=0.015)


def _stone(nt, bsdf, tint, roughness):
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, 0)
    n.inputs["Scale"].default_value = 3.0
    n.inputs["Detail"].default_value = 8.0
    n.inputs["Distortion"].default_value = 1.5         # veining
    nt.links.new(vec, n.inputs["Vector"])
    col = _ramp(nt, n.outputs["Fac"], _shade(tint, 0.7), _shade(tint, 1.0))
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.35)
    _bump(nt, bsdf, n.outputs["Fac"], 0.08)


def _metal(nt, bsdf, tint, roughness):
    bsdf.inputs["Base Color"].default_value = _shade(tint, 1.0)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = min(max(roughness, 0.15), 0.45)
    if "Anisotropic" in bsdf.inputs:       # brushed highlights, not chrome-ball
        bsdf.inputs["Anisotropic"].default_value = 0.5
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, -300)
    n.inputs["Scale"].default_value = 220.0            # faint brushed micro-relief
    nt.links.new(vec, n.inputs["Vector"])
    _bump(nt, bsdf, n.outputs["Fac"], 0.05)


def _fabric(nt, bsdf, tint, roughness):
    bsdf.inputs["Base Color"].default_value = _shade(tint, 1.0)
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.9)
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, -300)
    n.inputs["Scale"].default_value = 400.0            # fine weave
    n.inputs["Detail"].default_value = 2.0
    nt.links.new(vec, n.inputs["Vector"])
    _bump(nt, bsdf, n.outputs["Fac"], 0.3, distance=0.003)


def _grass(nt, bsdf, tint, roughness):
    vec = _proj(nt, 1.0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, 0)
    n.inputs["Scale"].default_value = 60.0
    n.inputs["Detail"].default_value = 6.0
    nt.links.new(vec, n.inputs["Vector"])
    col = _ramp(nt, n.outputs["Fac"],
                (0.04, 0.14, 0.03, 1.0), (0.12, 0.32, 0.07, 1.0))  # grass owns its green
    col = _weathered(nt, col, vec, 0.75, 1.15, scale=0.25)  # patchy lawn, not felt
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    _bump(nt, bsdf, n.outputs["Fac"], 0.2)


# First keyword hit wins, so order matters (brick before the generic "masonry";
# "waterproof" must stop BEFORE "water" matches; metal before "paint" so a
# painted-metal name stays metal). A `None` builder is a STOP entry: matched
# names keep the plain flat colour.
_LIBRARY = [
    (("brick",), _brick),
    (("roof tile", "terracotta", "shingle", "clay tile"), _roof_tile),
    (("tile", "ceramic", "porcelain", "mosaic", "glazed"), _tile),
    (("parquet", "plank", "floorboard", "decking", "timber floor",
      "wood floor", "flooring"), _planks),
    (("wood", "timber", "oak", "ply", "lumber", "mdf", "laminate", "veneer",
      "bamboo"), _wood),
    (("waterproof", "membrane", "damp proof", "vapour", "vapor"), None),
    (("water", "pool", "pond", "lake", "fountain"), _water),
    (("asphalt", "bitumen", "tarmac", "paving", "pavement", "road"), _asphalt),
    (("concrete", "cast-in", "cast in", "screed", "cement", "cmu", "precast"),
     _concrete),
    (("gravel", "ballast", "pebble", "scoria", "crushed rock"), _gravel),
    (("corrugat", "colorbond", "zincalume", "standing seam", "profiled metal"),
     _corrugated),
    (("metal", "steel", "alum", "copper", "brass", "bronze", "iron", "chrome",
      "zinc", "tin", "stainless", "metallic"), _metal),
    (("carpet", "fabric", "textile", "rug", "upholstery", "cloth", "felt",
      "acoustic"), _fabric),
    (("plaster", "stucco", "gypsum", "drywall", "plasterboard", "paint",
      "render"), _plaster),
    (("grass", "turf", "lawn", "vegetation", "planting"), _grass),
    (("stone", "marble", "granite", "masonry", "terrazzo", "slate"), _stone),
]


# Explicit surface builders, keyed for the N-panel override dropdown. "auto" (name
# match) and "plain" (flat colour) are handled by materials.build_material, not here.
SURFACES = {
    "brick": _brick, "wood": _wood, "planks": _planks, "concrete": _concrete,
    "stone": _stone, "tile": _tile, "roof_tile": _roof_tile, "metal": _metal,
    "corrugated": _corrugated, "fabric": _fabric, "grass": _grass,
    "plaster": _plaster, "asphalt": _asphalt, "gravel": _gravel,
    "water": _water,
}

# (key, label) pairs — the single source of truth for the override menu.
CHOICES = [
    ("brick", "Brick"), ("wood", "Wood"), ("planks", "Wood Floor / Decking"),
    ("concrete", "Concrete"), ("plaster", "Plaster / Paint"),
    ("tile", "Tile / Ceramic"), ("roof_tile", "Roof Tiles"),
    ("stone", "Stone / Marble"), ("metal", "Metal"),
    ("corrugated", "Corrugated Metal"), ("fabric", "Fabric / Carpet"),
    ("grass", "Grass"), ("asphalt", "Asphalt / Paving"),
    ("gravel", "Gravel"), ("water", "Water"),
]


def build_surface(nt, bsdf, key, tint, roughness):
    """Build one explicit library surface by key (the manual override path). Returns
    the key on success, None if the key is unknown."""
    fn = SURFACES.get((key or "").lower())
    if fn is None:
        return None
    fn(nt, bsdf, list(tint), float(roughness))
    return key


def category_for(name):
    """-> the library category name a Revit material maps to, or None."""
    if not name:
        return None
    low = name.lower()
    for keys, builder in _LIBRARY:
        for k in keys:
            if k in low:
                if builder is None:            # explicit stop: stays flat
                    return None
                return builder.__name__.lstrip("_")
    return None


def decorate(nt, bsdf, name, tint, roughness):
    """If `name` matches a library surface, build its procedural nodes onto `bsdf`
    (tinted by `tint`) and return the category name; else return None and leave the
    flat-colour material untouched."""
    if not name:
        return None
    low = name.lower()
    for keys, builder in _LIBRARY:
        for k in keys:
            if k in low:
                if builder is None:            # explicit stop: stays flat
                    return None
                builder(nt, bsdf, list(tint), float(roughness))
                return builder.__name__.lstrip("_")
    return None
