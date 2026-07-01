# SPDX-License-Identifier: MIT
"""Procedural volumetric clouds + atmosphere (the Blendit "Atmosphere / Weather").

Vendored from the standalone "Procedural Volumetric Clouds" add-on (Lewis, cooked
with Claude) that lives in Luitools/blender_clouds/cloud_generator.py, adapted into
Blendit's interactive session:

  * namespaced to `scene.bir_clouds` + `bir.clouds_*` operators so it never collides
    with the standalone add-on if that's also enabled in the user's Blender;
  * the add-on's single N-panel is replaced by Blendit-style COLLAPSIBLE sub-panels
    (defined in live.py); this module owns the settings, the operators, and the tuned
    node-graph logic;
  * "Add Sky & Sun" removes Blendit's default `Sun` lamp so there's one coherent key
    (no double-sun).

Density is the Guerrilla / Horizon-Zero-Dawn remap-and-erode technique in shader
nodes (see the original module's header + the blender_clouds/README.md). Cycles gives
the self-shadowing + silver lining that sell it; EEVEE previews are rougher.
"""
import bpy
from bpy.props import (
    EnumProperty, FloatProperty, IntProperty, BoolProperty, FloatVectorProperty,
)

DOMAIN_NAME = "Cloud_Domain"
MAT_NAME = "Cloud_Volume"

# ----------------------------------------------------------------------------
# Presets — each entry is shaped after a real cloud genus (fields map onto the
# PropertyGroup below).
# ----------------------------------------------------------------------------
PRESETS = {
    "CUMULUS_FAIR": {
        "label": "Fair-Weather Cumulus",
        "size": (380, 380, 110),   "altitude": 60,
        "shape_scale": 0.95,       "coverage": 0.40,   "density": 13.0,
        "detail": 12.0,            "roughness": 0.64,  "billow": 0.30,
        "billow_scale": 4.0,       "erosion": 0.30,    "erosion_scale": 11.0,
        "height_base": 0.05,       "height_top": 0.55, "anisotropy": 0.40,
        "evolve": 0.012,           "wind": (0.020, 0.006),
    },
    "CUMULUS_SCATTERED": {
        "label": "Scattered Cumulus",
        "size": (440, 440, 130),   "altitude": 55,
        "shape_scale": 0.85,       "coverage": 0.52,   "density": 16.0,
        "detail": 12.0,            "roughness": 0.66,  "billow": 0.32,
        "billow_scale": 4.2,       "erosion": 0.28,    "erosion_scale": 12.0,
        "height_base": 0.05,       "height_top": 0.60, "anisotropy": 0.42,
        "evolve": 0.015,           "wind": (0.025, 0.010),
    },
    "STRATOCUMULUS": {
        "label": "Stratocumulus (lumpy deck)",
        "size": (520, 520, 55),    "altitude": 45,
        "shape_scale": 0.7,        "coverage": 0.72,   "density": 11.0,
        "detail": 9.0,             "roughness": 0.58,  "billow": 0.35,
        "billow_scale": 3.5,       "erosion": 0.22,    "erosion_scale": 9.0,
        "height_base": 0.15,       "height_top": 0.80, "anisotropy": 0.28,
        "evolve": 0.008,           "wind": (0.018, 0.004),
    },
    "STRATUS_OVERCAST": {
        "label": "Stratus / Overcast",
        "size": (600, 600, 45),    "altitude": 40,
        "shape_scale": 0.55,       "coverage": 0.92,   "density": 9.0,
        "detail": 6.0,             "roughness": 0.48,  "billow": 0.10,
        "billow_scale": 2.5,       "erosion": 0.10,    "erosion_scale": 6.0,
        "height_base": 0.20,       "height_top": 0.85, "anisotropy": 0.14,
        "evolve": 0.004,           "wind": (0.012, 0.003),
    },
    "ALTOCUMULUS": {
        "label": "Altocumulus (regular cells)",
        "size": (460, 460, 40),    "altitude": 120,
        "shape_scale": 1.6,        "coverage": 0.60,   "density": 9.0,
        "detail": 8.0,             "roughness": 0.52,  "billow": 0.45,
        "billow_scale": 6.0,       "erosion": 0.25,    "erosion_scale": 14.0,
        "height_base": 0.20,       "height_top": 0.78, "anisotropy": 0.26,
        "evolve": 0.010,           "wind": (0.022, 0.008),
    },
    "CIRRUS": {
        "label": "Cirrus (high wispy streaks)",
        "size": (640, 640, 30),    "altitude": 200,
        "shape_scale": 0.9,        "coverage": 0.48,   "density": 8.0,
        "detail": 10.0,            "roughness": 0.74,  "billow": 0.05,
        "billow_scale": 2.0,       "erosion": 0.48,    "erosion_scale": 9.0,
        "height_base": 0.25,       "height_top": 0.75, "anisotropy": 0.50,
        "evolve": 0.020,           "wind": (0.060, 0.006),
        "stretch": (3.4, 1.0),
        "shear": (0.9, 0.1),
    },
    "CUMULONIMBUS": {
        "label": "Cumulonimbus (storm tower)",
        "size": (340, 340, 260),   "altitude": 90,
        "shape_scale": 0.8,        "coverage": 0.55,   "density": 18.0,
        "detail": 11.0,            "roughness": 0.70,  "billow": 0.35,
        "billow_scale": 3.2,       "erosion": 0.30,    "erosion_scale": 10.0,
        "height_base": 0.04,       "height_top": 0.94, "anisotropy": 0.34,
        "evolve": 0.014,           "wind": (0.018, 0.006),
        "shear": (0.45, 0.12),
    },
}

PRESET_ITEMS = [(k, v["label"], v["label"]) for k, v in PRESETS.items()]
QUALITY_ITEMS = [
    ("DRAFT",  "Draft (fast)",   "Coarse volume steps - fast viewport/preview"),
    ("MEDIUM", "Medium",          "Balanced quality and speed"),
    ("HIGH",   "High (final)",    "Fine volume steps - best quality, slower"),
]


# ----------------------------------------------------------------------------
# Property group
# ----------------------------------------------------------------------------
def _settings(context):
    return getattr(context.scene, "bir_clouds", None)


def _on_preset(self, context):
    apply_preset(context.scene.bir_clouds, self.preset)
    if self.live_update:
        bpy.ops.bir.clouds_generate()


def _on_param(self, context):
    if self.live_update and _domain_exists():
        bpy.ops.bir.clouds_generate()


def _on_atmo(self, context):
    # atmosphere sliders update the existing sky/sun live (no full cloud rebuild)
    apply_atmosphere(context, create=False)


class BIR_CloudSettings(bpy.types.PropertyGroup):
    preset: EnumProperty(name="Preset", items=PRESET_ITEMS, default="CUMULUS_FAIR",
                         update=_on_preset)
    quality: EnumProperty(name="Quality", items=QUALITY_ITEMS, default="MEDIUM")
    live_update: BoolProperty(name="Live Update", default=False,
                              description="Rebuild the cloud whenever a value changes")

    domain_shape: EnumProperty(
        name="Domain", default="BOX",
        items=[("BOX", "Box", "A rectangular slab of sky"),
               ("TORUS", "Ring (360)", "A ring of cloud around a centred camera - every "
                "direction shows an approaching storm. Great for cumulonimbus.")],
        update=_on_param)
    size: FloatVectorProperty(name="Domain Size", size=3, default=(380, 380, 110),
                              min=1.0, subtype="XYZ", update=_on_param)
    altitude: FloatProperty(name="Altitude", default=60.0, min=0.0, update=_on_param)

    ring_radius: FloatProperty(name="Ring Radius", default=520.0, min=10.0,
                               description="Distance from the centred camera to the storm wall",
                               update=_on_param)
    ring_tube: FloatProperty(name="Ring Thickness", default=170.0, min=5.0,
                             description="Horizontal depth of the cloud wall", update=_on_param)
    ring_height: FloatProperty(name="Ring Height", default=320.0, min=5.0,
                               description="Vertical extent of the storm wall", update=_on_param)
    ring_center_cam: BoolProperty(name="Centre Camera in Ring", default=True,
                                  description="Move the camera to the middle of the ring")

    shape_scale: FloatProperty(name="Shape Scale", default=0.95, min=0.05, soft_max=10,
                               description="Size of the main cloud masses (lower = bigger)",
                               update=_on_param)
    stretch: FloatVectorProperty(name="Stretch (X/Y)", size=2, default=(1.0, 1.0),
                                 min=0.05, update=_on_param,
                                 description="Anisotropic horizontal stretch (>1 = streaks)")
    shear: FloatVectorProperty(name="Wind Shear (X/Y)", size=2, default=(0.0, 0.0),
                               update=_on_param,
                               description="Lean the cloud with height - high values give a "
                                           "cumulonimbus anvil / sheared-off streaks")
    coverage: FloatProperty(name="Coverage", default=0.40, min=0.0, max=1.0,
                            description="Sky coverage / how much is filled", update=_on_param)
    density: FloatProperty(name="Density", default=13.0, min=0.0, soft_max=40,
                           update=_on_param)
    detail: FloatProperty(name="Detail", default=12.0, min=0.0, max=16.0,
                          description="Fractal octaves of the base noise", update=_on_param)
    roughness: FloatProperty(name="Roughness", default=0.64, min=0.0, max=1.0,
                             update=_on_param)
    billow: FloatProperty(name="Billow", default=0.30, min=0.0, max=1.0,
                          description="Cauliflower modulation - carves rounded worley valleys",
                          update=_on_param)
    billow_scale: FloatProperty(name="Billow Scale", default=4.0, min=0.05, soft_max=12,
                                description="Cauliflower bump frequency (higher = finer)",
                                update=_on_param)
    erosion: FloatProperty(name="Edge Erosion", default=0.30, min=0.0, max=1.0,
                           description="Carve wispy detail off the cloud edges",
                           update=_on_param)
    erosion_scale: FloatProperty(name="Erosion Scale", default=11.0, min=0.05, soft_max=30,
                                 update=_on_param)
    height_base: FloatProperty(name="Profile Base", default=0.05, min=0.0, max=1.0,
                               description="Where the cloud slab starts (0=floor)",
                               update=_on_param)
    height_top: FloatProperty(name="Profile Top", default=0.55, min=0.0, max=1.0,
                              description="Where the cloud slab fades out (1=ceiling)",
                              update=_on_param)
    anisotropy: FloatProperty(name="Anisotropy", default=0.40, min=-1.0, max=1.0,
                              description="Forward light scattering - the silver lining",
                              update=_on_param)

    animate: BoolProperty(name="Animate", default=False,
                          description="Drive wind drift + 4D noise evolution from frame")
    wind: FloatVectorProperty(name="Wind", size=2, default=(0.020, 0.006),
                              subtype="XYZ", update=_on_param)
    evolve: FloatProperty(name="Evolve Speed", default=0.012, min=0.0, soft_max=0.2,
                          description="How fast the cloud shapes churn over time",
                          update=_on_param)

    # --- atmosphere (live-updates the Nishita sky + sun) ---
    sun_elevation: FloatProperty(name="Sun Elevation", default=0.30, min=-0.15, max=1.5708,
                                 subtype="ANGLE", update=_on_atmo,
                                 description="Sun height. Low = warm, long light + silver rims")
    sun_azimuth: FloatProperty(name="Sun Azimuth", default=2.4, subtype="ANGLE",
                               update=_on_atmo, description="Sun compass direction")
    sun_strength: FloatProperty(name="Sun Strength", default=5.0, min=0.0, soft_max=20,
                                update=_on_atmo)
    sun_warmth: FloatProperty(name="Sun Warmth", default=0.5, min=0.0, max=1.0,
                              update=_on_atmo,
                              description="Golden-hour tint of the sunlight")
    sky_strength: FloatProperty(name="Sky Strength", default=1.0, min=0.0, soft_max=4.0,
                                update=_on_atmo,
                                description="Overall brightness of the sky / ambient fill")
    haze: FloatProperty(name="Haze (Air)", default=1.0, min=0.0, max=10.0, update=_on_atmo,
                        description="Air density - higher = hazier, bluer atmosphere")
    dust: FloatProperty(name="Dust", default=1.2, min=0.0, max=10.0, update=_on_atmo,
                        description="Aerosol/dust - higher = warmer, whiter horizon haze")
    exposure: FloatProperty(name="Exposure", default=0.0, min=-5.0, max=5.0, update=_on_atmo,
                            description="Overall image exposure (stops)")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def apply_preset(s, key):
    p = PRESETS[key]
    s.size = p["size"]
    s.altitude = p["altitude"]
    s.shape_scale = p["shape_scale"]
    s.stretch = p.get("stretch", (1.0, 1.0))
    s.shear = p.get("shear", (0.0, 0.0))
    s.coverage = p["coverage"]
    s.density = p["density"]
    s.detail = p["detail"]
    s.roughness = p["roughness"]
    s.billow = p["billow"]
    s.billow_scale = p["billow_scale"]
    s.erosion = p["erosion"]
    s.erosion_scale = p["erosion_scale"]
    s.height_base = p["height_base"]
    s.height_top = p["height_top"]
    s.anisotropy = p["anisotropy"]
    s.evolve = p["evolve"]
    s.wind = p["wind"]


def _domain_exists():
    return DOMAIN_NAME in bpy.data.objects


def _node(nt, ntype, name, x, y):
    n = nt.nodes.new(ntype)
    n.name = name
    n.label = name
    n.location = (x, y)
    return n


# ----------------------------------------------------------------------------
# Build the procedural volume material (verbatim tuned graph)
# ----------------------------------------------------------------------------
def build_material(s):
    mat = bpy.data.materials.get(MAT_NAME) or bpy.data.materials.new(MAT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    x = 0
    coord = _node(nt, "ShaderNodeTexCoord", "Coord", x, 0)

    sep = _node(nt, "ShaderNodeSeparateXYZ", "Sep Height", x + 200, -260)
    nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])

    x += 220
    mapping = _node(nt, "ShaderNodeMapping", "Cloud Mapping", x, 0)
    mapping.inputs["Location"].default_value = (0.0, 0.0, 0.0)
    base = s.shape_scale
    if s.domain_shape == "TORUS":
        base *= s.ring_radius / 200.0
    mapping.inputs["Scale"].default_value = (
        base * s.stretch[0], base * s.stretch[1], base)
    nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])

    zc = _node(nt, "ShaderNodeMath", "Shear Zc", x, -360)
    zc.operation = "SUBTRACT"
    zc.inputs[1].default_value = 0.5
    nt.links.new(sep.outputs["Z"], zc.inputs[0])
    sh_x = _node(nt, "ShaderNodeMath", "Shear X", x + 160, -300)
    sh_x.operation = "MULTIPLY"
    sh_x.inputs[1].default_value = s.shear[0]
    nt.links.new(zc.outputs["Value"], sh_x.inputs[0])
    sh_y = _node(nt, "ShaderNodeMath", "Shear Y", x + 160, -440)
    sh_y.operation = "MULTIPLY"
    sh_y.inputs[1].default_value = s.shear[1]
    nt.links.new(zc.outputs["Value"], sh_y.inputs[0])
    sh_vec = _node(nt, "ShaderNodeCombineXYZ", "Shear Vec", x + 320, -360)
    nt.links.new(sh_x.outputs["Value"], sh_vec.inputs["X"])
    nt.links.new(sh_y.outputs["Value"], sh_vec.inputs["Y"])
    sheared = _node(nt, "ShaderNodeVectorMath", "Sheared", x + 480, -140)
    sheared.operation = "ADD"
    nt.links.new(mapping.outputs["Vector"], sheared.inputs[0])
    nt.links.new(sh_vec.outputs["Vector"], sheared.inputs[1])
    sample = sheared.outputs["Vector"]

    x += 220
    noise = _node(nt, "ShaderNodeTexNoise", "Base Noise", x, 120)
    noise.noise_dimensions = "4D"
    noise.inputs["Scale"].default_value = 2.2
    noise.inputs["Detail"].default_value = s.detail
    noise.inputs["Roughness"].default_value = s.roughness
    noise.inputs["W"].default_value = 0.0
    nt.links.new(sample, noise.inputs["Vector"])

    vor = _node(nt, "ShaderNodeTexVoronoi", "Billow", x, -160)
    vor.feature = "SMOOTH_F1"
    vor.inputs["Scale"].default_value = s.billow_scale
    if "Smoothness" in vor.inputs:
        vor.inputs["Smoothness"].default_value = 0.92
    nt.links.new(sample, vor.inputs["Vector"])

    x += 220
    b_amt = _node(nt, "ShaderNodeMath", "Billow Amt", x, -200)
    b_amt.operation = "MULTIPLY"
    b_amt.inputs[1].default_value = s.billow
    nt.links.new(vor.outputs["Distance"], b_amt.inputs[0])

    b_mod = _node(nt, "ShaderNodeMath", "Billow Mod", x, -60)
    b_mod.operation = "SUBTRACT"
    b_mod.inputs[0].default_value = 1.0
    nt.links.new(b_amt.outputs["Value"], b_mod.inputs[1])

    x += 200
    shaped = _node(nt, "ShaderNodeMath", "Shaped", x, 0)
    shaped.operation = "MULTIPLY"
    nt.links.new(noise.outputs["Fac"], shaped.inputs[0])
    nt.links.new(b_mod.outputs["Value"], shaped.inputs[1])

    norm = _node(nt, "ShaderNodeMath", "Billow Norm", x + 180, 0)
    norm.operation = "MULTIPLY"
    norm.inputs[1].default_value = 1.0 / max(0.25, 1.0 - 0.5 * s.billow)
    nt.links.new(shaped.outputs["Value"], norm.inputs[0])

    x += 380
    cov = _node(nt, "ShaderNodeMapRange", "Coverage", x, 0)
    cov.clamp = True
    cov.inputs["From Min"].default_value = 1.0 - s.coverage
    cov.inputs["From Max"].default_value = 1.0
    cov.inputs["To Min"].default_value = 0.0
    cov.inputs["To Max"].default_value = 1.0
    nt.links.new(norm.outputs["Value"], cov.inputs["Value"])

    ero1 = _node(nt, "ShaderNodeTexVoronoi", "Erosion Tex", x, -220)
    ero1.feature = "F1"
    ero1.inputs["Scale"].default_value = s.erosion_scale
    nt.links.new(sample, ero1.inputs["Vector"])
    ero2 = _node(nt, "ShaderNodeTexVoronoi", "Erosion Tex 2", x, -380)
    ero2.feature = "F1"
    ero2.inputs["Scale"].default_value = s.erosion_scale * 2.7
    nt.links.new(sample, ero2.inputs["Vector"])

    x += 180
    w1 = _node(nt, "ShaderNodeMath", "Ero W1", x, -200)
    w1.operation = "MULTIPLY"; w1.inputs[1].default_value = 0.7
    nt.links.new(ero1.outputs["Distance"], w1.inputs[0])
    w2 = _node(nt, "ShaderNodeMath", "Ero W2", x, -340)
    w2.operation = "MULTIPLY"; w2.inputs[1].default_value = 0.3
    nt.links.new(ero2.outputs["Distance"], w2.inputs[0])

    x += 180
    ero_field = _node(nt, "ShaderNodeMath", "Ero Field", x, -260)
    ero_field.operation = "ADD"
    nt.links.new(w1.outputs["Value"], ero_field.inputs[0])
    nt.links.new(w2.outputs["Value"], ero_field.inputs[1])

    ero_amt = _node(nt, "ShaderNodeMath", "Erosion Amt", x + 160, -260)
    ero_amt.operation = "MULTIPLY"
    ero_amt.inputs[1].default_value = s.erosion
    nt.links.new(ero_field.outputs["Value"], ero_amt.inputs[0])

    eroded = _node(nt, "ShaderNodeMath", "Eroded", x, 0)
    eroded.operation = "SUBTRACT"
    nt.links.new(cov.outputs["Result"], eroded.inputs[0])
    nt.links.new(ero_amt.outputs["Value"], eroded.inputs[1])

    ramp = _node(nt, "ShaderNodeValToRGB", "Height Profile", x, -480)
    cr = ramp.color_ramp
    cr.interpolation = "B_SPLINE"
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0, 0, 0, 1)
    e_base = cr.elements.new(max(0.001, min(s.height_base, s.height_top - 0.02)))
    e_base.color = (1, 1, 1, 1)
    e_top = cr.elements.new(max(s.height_base + 0.02, s.height_top))
    e_top.color = (1, 1, 1, 1)
    e_ceil = cr.elements.new(1.0)
    e_ceil.color = (0, 0, 0, 1)
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])

    x += 200
    masked = _node(nt, "ShaderNodeMath", "Masked", x, 0)
    masked.operation = "MULTIPLY"
    nt.links.new(eroded.outputs["Value"], masked.inputs[0])
    nt.links.new(ramp.outputs["Color"], masked.inputs[1])

    if s.domain_shape == "TORUS":
        edge_masked = masked
    else:
        margin = 0.14

        def _axis_fade(axis_socket, label, yy):
            inv = _node(nt, "ShaderNodeMath", "EdgeInv " + label, x - 200, yy)
            inv.operation = "SUBTRACT"
            inv.inputs[0].default_value = 1.0
            nt.links.new(axis_socket, inv.inputs[1])
            mn = _node(nt, "ShaderNodeMath", "EdgeMin " + label, x - 40, yy)
            mn.operation = "MINIMUM"
            nt.links.new(axis_socket, mn.inputs[0])
            nt.links.new(inv.outputs["Value"], mn.inputs[1])
            fade = _node(nt, "ShaderNodeMapRange", "EdgeFade " + label, x + 120, yy)
            fade.clamp = True
            fade.inputs["From Min"].default_value = 0.0
            fade.inputs["From Max"].default_value = margin
            nt.links.new(mn.outputs["Value"], fade.inputs["Value"])
            return fade

        fx = _axis_fade(sep.outputs["X"], "X", -640)
        fy = _axis_fade(sep.outputs["Y"], "Y", -820)
        edge = _node(nt, "ShaderNodeMath", "Edge Mask", x + 320, -720)
        edge.operation = "MULTIPLY"
        nt.links.new(fx.outputs["Result"], edge.inputs[0])
        nt.links.new(fy.outputs["Result"], edge.inputs[1])

        edge_masked = _node(nt, "ShaderNodeMath", "Edge Masked", x + 180, 0)
        edge_masked.operation = "MULTIPLY"
        nt.links.new(masked.outputs["Value"], edge_masked.inputs[0])
        nt.links.new(edge.outputs["Value"], edge_masked.inputs[1])

    x += 380
    clamp = _node(nt, "ShaderNodeMath", "Clamp", x, 0)
    clamp.operation = "MAXIMUM"
    clamp.inputs[1].default_value = 0.0
    nt.links.new(edge_masked.outputs["Value"], clamp.inputs[0])

    final = _node(nt, "ShaderNodeMath", "Density Mul", x, -180)
    final.operation = "MULTIPLY"
    final.inputs[1].default_value = s.density
    nt.links.new(clamp.outputs["Value"], final.inputs[0])

    x += 200
    vol = _node(nt, "ShaderNodeVolumePrincipled", "Cloud Volume", x, 0)
    vol.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    vol.inputs["Anisotropy"].default_value = s.anisotropy
    nt.links.new(final.outputs["Value"], vol.inputs["Density"])

    out = _node(nt, "ShaderNodeOutputMaterial", "Output", x + 220, 0)
    nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])

    _setup_drivers(nt, s)
    return mat


def _setup_drivers(nt, s):
    """Wind drift on the Mapping location + 4D evolution on the noise W."""
    map_path = 'nodes["Cloud Mapping"].inputs[1].default_value'
    noise = nt.nodes["Base Noise"]
    w_path = 'nodes["Base Noise"].inputs[%d].default_value' % noise.inputs.find("W")

    for idx in (0, 1, 2):
        try:
            nt.driver_remove(map_path, idx)
        except Exception:
            pass
    try:
        nt.driver_remove(w_path)
    except Exception:
        pass

    if not s.animate:
        return

    for idx, speed in ((0, s.wind[0]), (1, s.wind[1])):
        fc = nt.driver_add(map_path, idx)
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = "frame * %.6f" % speed
    fc = nt.driver_add(w_path)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = "frame * %.6f" % s.evolve


# ----------------------------------------------------------------------------
# Domain + render settings + atmosphere
# ----------------------------------------------------------------------------
def build_domain(context, s):
    """Create/replace the cloud domain object and assign the volume material."""
    import bmesh
    old = bpy.data.objects.get(DOMAIN_NAME)
    if old is not None:
        me = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)

    if s.domain_shape == "TORUS":
        bpy.ops.mesh.primitive_torus_add(
            major_radius=s.ring_radius, minor_radius=s.ring_tube,
            major_segments=72, minor_segments=24, align="WORLD",
            location=(0.0, 0.0, 0.0))
        obj = context.active_object
        obj.name = DOMAIN_NAME
        obj.data.name = DOMAIN_NAME
        obj.scale = (1.0, 1.0, max(0.02, s.ring_height / (2.0 * s.ring_tube)))
        obj.location = (0.0, 0.0, s.altitude + s.ring_height * 0.5)
    else:
        mesh = bpy.data.meshes.new(DOMAIN_NAME)
        obj = bpy.data.objects.new(DOMAIN_NAME, mesh)
        context.collection.objects.link(obj)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(mesh)
        bm.free()
        obj.scale = (s.size[0], s.size[1], s.size[2])
        obj.location = (0.0, 0.0, s.altitude + s.size[2] * 0.5)

    obj.display_type = "WIRE"
    obj.hide_render = False
    obj.visible_shadow = True

    mat = build_material(s)
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    if s.domain_shape == "TORUS" and s.ring_center_cam:
        cam = context.scene.camera or bpy.data.objects.get("Camera")
        if cam is not None:
            cam.location = (0.0, 0.0, s.altitude + s.ring_height * 0.45)
            cam.rotation_euler = (1.5708, 0.0, 0.0)
            if cam.data:
                cam.data.clip_end = max(cam.data.clip_end, s.ring_radius * 3.0)
    return obj


def apply_render_settings(context, quality):
    scene = context.scene
    eng = scene.render.engine
    step = {"DRAFT": 4.0, "MEDIUM": 1.0, "HIGH": 0.4}[quality]

    if eng == "CYCLES":
        cy = scene.cycles
        cy.volume_step_rate = step
        cy.volume_preview_step_rate = max(step, 2.0)
        cy.volume_max_steps = 1024
        cy.volume_bounces = 2
    elif eng.startswith("BLENDER_EEVEE"):
        ev = scene.eevee
        samples = {"DRAFT": 32, "MEDIUM": 64, "HIGH": 128}[quality]
        try:
            ev.volumetric_samples = samples
            ev.volumetric_tile_size = "8" if quality == "HIGH" else "16"
            ev.volumetric_start = 0.1
            ev.volumetric_end = 1000.0
            ev.use_volumetric_shadows = True
        except Exception:
            pass


def apply_atmosphere(context, create=False):
    """Nishita sky + one coherent Sun lamp, driven live by the panel. Removes
    Blendit's default `Sun` so there is a single key light (no double-sun)."""
    import math
    scene = context.scene
    s = scene.bir_clouds

    world = scene.world
    if world is None:
        if not create:
            return
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    wt = world.node_tree

    sky = wt.nodes.get("Cloud Sky")
    bg = wt.nodes.get("Cloud BG")
    if sky is None or bg is None:
        if not create:
            return
        wt.nodes.clear()
        sky = wt.nodes.new("ShaderNodeTexSky"); sky.name = "Cloud Sky"; sky.location = (-300, 0)
        bg = wt.nodes.new("ShaderNodeBackground"); bg.name = "Cloud BG"; bg.location = (0, 0)
        out = wt.nodes.new("ShaderNodeOutputWorld"); out.location = (220, 0)
        wt.links.new(sky.outputs[0], bg.inputs["Color"])
        wt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    def _set(node, attr, val):
        if hasattr(node, attr):
            try:
                setattr(node, attr, val)
            except Exception:
                pass

    for st in ("MULTIPLE_SCATTERING", "NISHITA"):
        try:
            sky.sky_type = st
            break
        except Exception:
            continue
    _set(sky, "sun_disc", False)
    _set(sky, "sun_elevation", s.sun_elevation)
    _set(sky, "sun_rotation", s.sun_azimuth)
    _set(sky, "altitude", 300.0)
    _set(sky, "air_density", s.haze)
    _set(sky, "aerosol_density", s.dust)
    _set(sky, "dust_density", s.dust)
    bg.inputs["Strength"].default_value = s.sky_strength

    # Blendit's setup_world drops a lamp named "Sun"; retire it so there's one key.
    for o in list(bpy.data.objects):
        if o.name == "Sun" and getattr(o, "data", None) is not None \
                and getattr(o.data, "type", None) == "SUN":
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass

    lamp = bpy.data.lights.get("Cloud_Sun") or bpy.data.lights.new("Cloud_Sun", "SUN")
    lamp.type = "SUN"
    lamp.energy = s.sun_strength
    lamp.angle = 0.012
    warm = s.sun_warmth * max(0.0, 1.0 - s.sun_elevation / 1.2)
    lamp.color = (1.0, 1.0 - 0.14 * warm, 1.0 - 0.34 * warm)
    sun = bpy.data.objects.get("Cloud_Sun")
    if sun is None:
        sun = bpy.data.objects.new("Cloud_Sun", lamp)
        context.collection.objects.link(sun)
    sun.rotation_euler = (math.pi / 2.0 - s.sun_elevation, 0.0, s.sun_azimuth)

    scene.view_settings.exposure = s.exposure


# ----------------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------------
class BIR_OT_clouds_generate(bpy.types.Operator):
    bl_idname = "bir.clouds_generate"
    bl_label = "Generate / Update Clouds"
    bl_description = "Create or rebuild the cloud domain and procedural volume material"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.bir_clouds
        build_domain(context, s)
        apply_render_settings(context, s.quality)
        self.report({"INFO"}, "Clouds generated (%s)" % PRESETS[s.preset]["label"])
        return {"FINISHED"}


class BIR_OT_clouds_add_sky(bpy.types.Operator):
    bl_idname = "bir.clouds_add_sky"
    bl_label = "Add / Update Sky & Sun"
    bl_description = "Add a Nishita sky world + coherent Sun lamp, driven by the Atmosphere panel"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        apply_atmosphere(context, create=True)
        self.report({"INFO"}, "Sky & Sun updated")
        return {"FINISHED"}


class BIR_OT_clouds_quality(bpy.types.Operator):
    bl_idname = "bir.clouds_quality"
    bl_label = "Apply Render Quality"
    bl_description = "Apply volume step / sample settings for the current engine"

    def execute(self, context):
        apply_render_settings(context, context.scene.bir_clouds.quality)
        self.report({"INFO"}, "Render quality applied (%s)" % context.scene.bir_clouds.quality)
        return {"FINISHED"}


# Non-panel classes registered by live.py (panels live there, next to _Sub).
CLOUD_CLASSES = (
    BIR_CloudSettings,
    BIR_OT_clouds_generate,
    BIR_OT_clouds_add_sky,
    BIR_OT_clouds_quality,
)
