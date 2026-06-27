"""White / Clay - a clean white massing model.

The fix for "white wasn't white": the blue Nishita sky + AgX + the dim base
exposure used to grey it out. White now uses a bright NEUTRAL environment (no blue
cast), a soft key for gentle form-reading shadows, and the Standard view transform
so white renders as white.
"""
from ..materials import make_clay_material, override_all
from .registry import register_preset
from . import _helpers


def apply(loaded, spec):
    _helpers.clear_npr()
    override_all(loaded, make_clay_material("WhiteClay", value=0.9, roughness=0.6))
    _helpers.set_neutral_world(0.6, 1.0)    # even neutral fill (no blue), not blinding
    _helpers.set_sun_energy(2.0)            # soft key -> gentle form shadows
    _helpers.set_sun_softness(4.0)          # diffuse shadow edges
    _helpers.set_ground_tone(0.92)          # ground a touch brighter -> model reads
    _helpers.set_view("AgX", 0.4)           # filmic rolloff keeps white white, form intact


register_preset("white", apply)
