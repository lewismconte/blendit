"""Watercolor - a painted architectural wash. Not a flat fill: the massing is
posterised into a warm-light / cool-shadow pigment ramp (EEVEE Shader-to-RGB),
then given the tells that make watercolour read as *painted* -

  * paper tooth      - a screen-space grain so the 'paper' is one consistent sheet,
  * granulation      - object-space mottle where pigment settles,
  * wet edges        - pigment pooling (darker, richer) at the silhouettes,

under loose thin sepia ink lines the colour spills past. All in the shader (Blender
5.x gutted the compositor), so it needs no post. Renders under EEVEE (Shader-to-RGB).
"""
import bpy

from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all

_ZENITH = (0.60, 0.71, 0.86)    # cool blue at the top of frame
_HORIZON = (0.98, 0.95, 0.87)   # warm cream at the bottom


def _watercolor_material(name="BIR_Watercolor"):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    add, link = nt.nodes.new, nt.links.new

    out = add("ShaderNodeOutputMaterial")
    out.location = (1500, 0)
    emi = add("ShaderNodeEmission")
    emi.location = (1300, 0)
    link(emi.outputs["Emission"], out.inputs["Surface"])

    # --- lit tone (0..1) via Shader-to-RGB: this is what gives the wash its form ---
    diff = add("ShaderNodeBsdfDiffuse")
    diff.location = (-1100, 220)
    diff.inputs["Color"].default_value = (0.85, 0.85, 0.85, 1.0)
    s2r = add("ShaderNodeShaderToRGB")
    s2r.location = (-920, 220)
    link(diff.outputs["BSDF"], s2r.inputs["Shader"])
    bw = add("ShaderNodeRGBToBW")
    bw.location = (-740, 220)
    link(s2r.outputs["Color"], bw.inputs["Color"])

    # --- warm-light / cool-shadow pigment ramp (smooth, painterly) ---
    ramp = add("ShaderNodeValToRGB")
    ramp.location = (-560, 220)
    cr = ramp.color_ramp
    cr.interpolation = "B_SPLINE"
    e = cr.elements
    e[0].position, e[0].color = 0.0, (0.28, 0.34, 0.52, 1.0)   # deep cool shadow (richer)
    e[1].position, e[1].color = 1.0, (0.96, 0.90, 0.77, 1.0)   # warm ochre light (not chalk)
    m1 = e.new(0.32)
    m1.color = (0.50, 0.54, 0.63, 1.0)                          # cool grey-blue mid
    m2 = e.new(0.66)
    m2.color = (0.87, 0.71, 0.49, 1.0)                          # richer warm sienna mid
    link(bw.outputs["Val"], ramp.inputs["Fac"])
    wash = ramp.outputs["Color"]

    tc = add("ShaderNodeTexCoord")
    tc.location = (-1100, -260)

    # --- paper tooth: screen-space grain, so the sheet is consistent everywhere ---
    paper_n = add("ShaderNodeTexNoise")
    paper_n.location = (-740, -160)
    paper_n.inputs["Scale"].default_value = 70.0
    paper_n.inputs["Detail"].default_value = 1.5
    link(tc.outputs["Window"], paper_n.inputs["Vector"])
    paper_r = add("ShaderNodeValToRGB")
    paper_r.location = (-560, -160)
    paper_r.color_ramp.elements[0].position = 0.30
    paper_r.color_ramp.elements[0].color = (0.92, 0.92, 0.92, 1.0)
    paper_r.color_ramp.elements[1].position = 0.72
    paper_r.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    link(paper_n.outputs["Fac"], paper_r.inputs["Fac"])

    # --- granulation: object-space pigment settling (bigger, softer) ---
    gran_n = add("ShaderNodeTexNoise")
    gran_n.location = (-740, -460)
    gran_n.inputs["Scale"].default_value = 5.0
    gran_n.inputs["Detail"].default_value = 3.0
    link(tc.outputs["Object"], gran_n.inputs["Vector"])
    gran_r = add("ShaderNodeValToRGB")
    gran_r.location = (-560, -460)
    gran_r.color_ramp.elements[0].position = 0.28
    gran_r.color_ramp.elements[0].color = (0.88, 0.88, 0.88, 1.0)
    gran_r.color_ramp.elements[1].position = 0.78
    gran_r.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    link(gran_n.outputs["Fac"], gran_r.inputs["Fac"])

    # wash * paper * granulation
    mul1 = add("ShaderNodeMixRGB")
    mul1.location = (-260, 40)
    mul1.blend_type = "MULTIPLY"
    mul1.inputs["Fac"].default_value = 1.0
    link(wash, mul1.inputs["Color1"])
    link(paper_r.outputs["Color"], mul1.inputs["Color2"])
    mul2 = add("ShaderNodeMixRGB")
    mul2.location = (-60, 40)
    mul2.blend_type = "MULTIPLY"
    mul2.inputs["Fac"].default_value = 1.0
    link(mul1.outputs["Color"], mul2.inputs["Color1"])
    link(gran_r.outputs["Color"], mul2.inputs["Color2"])
    textured = mul2.outputs["Color"]

    # --- wet edges: pigment pools darker + richer at the silhouettes ---
    lw = add("ShaderNodeLayerWeight")
    lw.location = (-60, 420)
    lw.inputs["Blend"].default_value = 0.30
    edge_r = add("ShaderNodeValToRGB")
    edge_r.location = (140, 420)
    edge_r.color_ramp.elements[0].position = 0.0     # grazing (silhouette) -> mask 1
    edge_r.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
    edge_r.color_ramp.elements[1].position = 0.38    # facing the camera -> mask 0
    edge_r.color_ramp.elements[1].color = (0.0, 0.0, 0.0, 1.0)
    link(lw.outputs["Facing"], edge_r.inputs["Factor"])
    darkpig = add("ShaderNodeHueSaturation")
    darkpig.location = (140, 120)
    darkpig.inputs["Saturation"].default_value = 1.4
    darkpig.inputs["Value"].default_value = 0.52     # a richer pooled-pigment rim
    link(textured, darkpig.inputs["Color"])
    edgemix = add("ShaderNodeMixRGB")
    edgemix.location = (500, 160)
    edgemix.blend_type = "MIX"
    link(edge_r.outputs["Color"], edgemix.inputs["Fac"])
    link(textured, edgemix.inputs["Color1"])
    link(darkpig.outputs["Color"], edgemix.inputs["Color2"])

    # a gentle overall saturation lift so the pigment stays lively, not muddy
    sat = add("ShaderNodeHueSaturation")
    sat.location = (900, 160)
    sat.inputs["Saturation"].default_value = 1.18
    link(edgemix.outputs["Color"], sat.inputs["Color"])
    link(sat.outputs["Color"], emi.inputs["Color"])
    return mat


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()                            # Standard -> the pigment reads true
    mat = _watercolor_material()
    override_all(loaded, mat)
    # Same wash on the ground, so the building's cast shadow becomes a cool wash pool.
    _helpers.set_ground_material(mat)
    npr.show_ground()
    # A soft blue->cream watercolour sky behind it (dim to the lighting, so the sun
    # still shapes the pigment ramp cleanly).
    npr.set_camera_ray_world(gradient=(_HORIZON, _ZENITH), ambient=0.20)
    _helpers.aim_sun(42.0, 205.0)                  # front catches warm light, a side stays
    _helpers.set_sun_energy(3.6)                   # cool -> a warm/cool balance across the form
    _helpers.set_sun_softness(2.0)
    # Loose thin sepia ink the wash runs past.
    npr.setup_line_art(radius=npr.default_line_radius() * 0.8,
                       color=(0.34, 0.26, 0.20), crease_deg=55.0,
                       thickness_factor=1.0)
    npr.set_sketchiness(0.35)                      # a little hand wobble
    npr.set_line_overshoot(0.05)


register_preset("watercolor", apply)
