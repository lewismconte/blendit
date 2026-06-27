"""Shadow study - a sun study: neutral clay, one strong crisp sun, dim fill, so the
shadow pattern reads dramatically across the form and the ground. Distinct from
White (which has soft even light and no cast drama) by its high contrast."""
from ..materials import make_clay_material, override_all
from .registry import register_preset
from . import _helpers


def apply(loaded, spec):
    _helpers.clear_npr()
    override_all(loaded, make_clay_material("ShadowClay", value=0.78, roughness=0.8))
    _helpers.set_neutral_world(0.4, 0.55)   # dim neutral fill -> deep, legible shadows
    _helpers.set_sun_energy(5.0)            # strong directional key
    _helpers.set_sun_softness(0.5)          # crisp, sun-accurate shadow edges
    _helpers.set_ground_tone(0.6)
    _helpers.set_view("AgX", -0.2)          # filmic; bright lit side, deep shade


register_preset("shadow", apply)
