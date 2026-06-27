"""Specular / Lookdev - check materials by their reflections: real materials forced
glossy, a brighter sky/env for something to reflect, and a darker filmic exposure
so highlights and reflections pop. Distinct from Realistic (matte PBR) by the
mirror-like surfaces."""
from ..materials import apply_materials
from .registry import register_preset
from . import _helpers


def apply(loaded, spec):
    _helpers.clear_npr()
    engine = str(spec.get("render", {}).get("engine", "CYCLES")).upper()
    apply_materials(loaded, engine=engine)
    _helpers.set_glossiness(loaded, 0.05)   # near-mirror -> obvious reflective lookdev
    _helpers.set_world_strength(1.3)        # bright sky -> something to reflect
    _helpers.set_view("AgX", -1.1)          # darker so highlights/reflections pop


register_preset("specular", apply)
