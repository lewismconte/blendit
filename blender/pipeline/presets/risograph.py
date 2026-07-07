"""Risograph - the two-tone print look: the shaded model posterised into three hard
riso spot-ink bands (midnight blue in the deep shade, fluoro pink in the mids, cream
paper in the light). Done in the material via an EEVEE Shader-to-RGB tone ramp (the
same trick as Cel), so it needs no compositor - flat emission bands = the spot-ink feel.

Grain, halftone dots and channel misregistration are the documented follow-ups (they
need the compositor, which Blender 5.x rebuilt as a node group). Renders under EEVEE.
"""
import bpy

from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all

_CREAM = (0.96, 0.92, 0.82)
_PINK = (0.96, 0.38, 0.52)
_BLUE = (0.16, 0.26, 0.58)


def _riso_material(name="BIR_Riso"):
    """Flat 3-band duotone keyed off the lit tone: deep shade -> blue, mid -> pink,
    light -> cream. Hard CONSTANT bands give the posterised spot-ink look."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-300, 0)
    diff.inputs["Color"].default_value = (0.92, 0.92, 0.92, 1.0)
    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    s2r.location = (-100, 0)
    nt.links.new(diff.outputs["BSDF"], s2r.inputs["Shader"])
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    bw.location = (60, 0)
    nt.links.new(s2r.outputs["Color"], bw.inputs["Color"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (240, 0)
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    # Stops sit in ShaderToRGB's actual output range on architectural surfaces
    # (EEVEE's diffuse probe tops out well under 1.0): deep shade -> blue, the grazed
    # mids -> pink, the sunlit faces -> cream.
    cr.elements[0].position = 0.0
    cr.elements[0].color = _BLUE + (1.0,)
    cr.elements[1].position = 0.52
    cr.elements[1].color = _CREAM + (1.0,)
    mid = cr.elements.new(0.26)
    mid.color = _PINK + (1.0,)
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.location = (440, 0)
    nt.links.new(ramp.outputs["Color"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()                        # Standard -> the flat inks read true
    mat = _riso_material()
    override_all(loaded, mat)
    # Same ink treatment on the ground, so the building's cast shadow becomes a
    # coloured band rather than a grey blob.
    g = bpy.data.objects.get("BIR_Ground")
    if g is not None and getattr(g, "type", None) == "MESH":
        g.data.materials.clear()
        g.data.materials.append(mat)
    npr.show_ground()
    # Flat cream paper to the camera, near-black to lighting -> the sun alone shapes a
    # wide light->shade range, so all three ink bands appear (not one flat mid tone).
    npr.set_camera_ray_world(_CREAM, ambient=0.06, strength=1.0)
    _helpers.aim_sun(26.0, 130.0)              # low raking key -> wide light->shade range
    _helpers.set_sun_energy(5.5)               # sun-dominant so all three bands appear
    _helpers.set_sun_softness(0.7)
    # A thin blue spot-ink keyline so the massing always reads as a graphic shape,
    # even where the tonal bands sit close together (a riso-poster staple).
    npr.setup_line_art(radius=npr.default_line_radius() * 0.8,
                       color=_BLUE, crease_deg=70.0, thickness_factor=1.0)


register_preset("risograph", apply)
