"""Realistic - the photoreal default: full PBR materials under the physical sun + sky
(the blue Nishita sky is correct here) with the AgX filmic transform. The real
material colours are what set this apart from the monochrome clay modes."""
from ..materials import apply_materials
from .registry import register_preset
from . import _helpers


def apply(loaded, spec):
    _helpers.clear_npr()
    engine = str(spec.get("render", {}).get("engine", "CYCLES")).upper()
    apply_materials(loaded, engine=engine)
    _helpers.set_view("AgX", -0.35)         # filmic; keeps the sun+sky from setup_world


register_preset("realistic", apply)
