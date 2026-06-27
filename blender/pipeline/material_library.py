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
def _brick_node(nt, tint, vec, loc):
    """One Brick texture (the 2-D pattern) fed a real-world-scaled vector."""
    b = nt.nodes.new("ShaderNodeTexBrick")
    b.location = loc
    b.inputs["Scale"].default_value = 1.0
    b.inputs["Brick Width"].default_value = 0.215      # metres (real brick)
    b.inputs["Row Height"].default_value = 0.065
    b.inputs["Mortar Size"].default_value = 0.006
    b.inputs["Mortar Smooth"].default_value = 0.1
    b.inputs["Color1"].default_value = _shade(tint, 1.0)
    b.inputs["Color2"].default_value = _shade(tint, 0.72)
    b.inputs["Mortar"].default_value = (0.05, 0.05, 0.05, 1.0)
    b.offset_frequency = 2
    nt.links.new(vec, b.inputs["Vector"])
    return b


def _brick(nt, bsdf, tint, roughness):
    """Brick is the one 2-D texture in the library (the Brick node only uses X,Y),
    so a plain projection collapses to a stripe on vertical walls. Triplanar-project
    it: brick the XY / XZ / YZ planes and blend by |true normal|, so it reads
    correctly on a wall facing any direction and on floors - no UVs, no image."""
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
    bz = _brick_node(nt, tint, vz, (-450, 300))
    by = _brick_node(nt, tint, vy, (-450, 0))
    bx = _brick_node(nt, tint, vx, (-450, -300))

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

    def _scale(color, w, y):
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

    blended = _vadd(_vadd(_scale(bx.outputs["Color"], wx, -300),
                          _scale(by.outputs["Color"], wy, 0), -150),
                    _scale(bz.outputs["Color"], wz, 300), 0)
    nt.links.new(blended, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.85)

    # subtle orientation-independent relief (3-D noise, so no projection issue)
    nb = nt.nodes.new("ShaderNodeTexNoise")
    nb.location = (-450, 500)
    nb.inputs["Scale"].default_value = 40.0
    nt.links.new(mp.outputs["Vector"], nb.inputs["Vector"])
    _bump(nt, bsdf, nb.outputs["Fac"], 0.12)


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
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = max(roughness, 0.8)
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.location = (-400, -300)
    fine.inputs["Scale"].default_value = 35.0
    nt.links.new(vec, fine.inputs["Vector"])
    _bump(nt, bsdf, fine.outputs["Fac"], 0.1)


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
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    _bump(nt, bsdf, n.outputs["Fac"], 0.2)


# First keyword hit wins, so order matters (brick before the generic "masonry").
_LIBRARY = [
    (("brick",), _brick),
    (("wood", "timber", "oak", "ply", "lumber", "mdf", "laminate", "veneer",
      "bamboo", "parquet"), _wood),
    (("concrete", "cast-in", "cast in", "screed", "cement", "cmu", "precast"),
     _concrete),
    (("metal", "steel", "alum", "copper", "brass", "bronze", "iron", "chrome",
      "zinc", "tin", "stainless", "metallic"), _metal),
    (("carpet", "fabric", "textile", "rug", "upholstery", "cloth", "felt",
      "acoustic"), _fabric),
    (("grass", "turf", "lawn", "vegetation", "planting"), _grass),
    (("stone", "marble", "granite", "stucco", "plaster", "masonry", "tile",
      "ceramic", "porcelain", "terrazzo", "slate", "render"), _stone),
]


# Explicit surface builders, keyed for the N-panel override dropdown. "auto" (name
# match) and "plain" (flat colour) are handled by materials.build_material, not here.
SURFACES = {
    "brick": _brick, "wood": _wood, "concrete": _concrete, "stone": _stone,
    "metal": _metal, "fabric": _fabric, "grass": _grass,
}

# (key, label) pairs — the single source of truth for the override menu.
CHOICES = [
    ("brick", "Brick"), ("wood", "Wood"), ("concrete", "Concrete"),
    ("stone", "Stone / Tile"), ("metal", "Metal"), ("fabric", "Fabric / Carpet"),
    ("grass", "Grass"),
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
                builder(nt, bsdf, list(tint), float(roughness))
                return builder.__name__.lstrip("_")
    return None
