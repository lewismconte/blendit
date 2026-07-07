"""White / Clay - a clean white massing model.

The fix for "white wasn't white": the blue Nishita sky + AgX + the dim base
exposure used to grey it out. White uses a NEUTRAL environment (no blue cast) and
the AgX rolloff so white renders as white. A soft light-grey gradient backdrop
(darker zenith -> bright horizon) gives the model something to separate against, so
it reads as a crisp museum massing model instead of vanishing into a flat grey field.
"""
from ..materials import make_clay_material, override_all
from .registry import register_preset
from . import _helpers


def apply(loaded, spec):
    _helpers.clear_npr()
    override_all(loaded, make_clay_material("WhiteClay", value=0.95, roughness=0.6))
    _helpers.set_gradient_world(zenith=0.30, horizon=0.72, strength=1.0)
    _helpers.set_sun_energy(2.6)            # firm-but-soft key -> gentle form shadows
    _helpers.set_sun_softness(2.2)          # softer than a sun study, still legible edges
    _helpers.set_ground_tone(0.86)          # light floor, a hair under the horizon -> base reads
    _helpers.set_view("AgX", 0.4)           # filmic rolloff keeps white white, form intact


register_preset("white", apply)
