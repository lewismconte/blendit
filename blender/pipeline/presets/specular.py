"""Specular / Showroom - the lookdev mode, now visually its OWN thing (it used
to read as a twin of Realistic on the contact sheet): a dark studio-gradient
environment with a glowing horizon band, the real materials forced glossy, a
big soft key light, and a dark reflective floor. Reads material character and
reflections - a product-shot of the building, not a site photo."""
from ..materials import apply_materials
from .registry import register_preset
from . import _helpers


def apply(loaded, spec):
    _helpers.clear_npr()
    engine = str(spec.get("render", {}).get("engine", "CYCLES")).upper()
    apply_materials(loaded, engine=engine)
    _helpers.set_glossiness(loaded, 0.08)   # glossy, just short of mirror
    _helpers.set_studio_world()             # dark gradient + horizon glow
    _helpers.set_sun_energy(2.0)            # soft studio key, not daylight
    _helpers.set_sun_softness(4.0)          # big source -> soft shadows
    _helpers.set_ground_finish(0.03, 0.12)  # the dark reflective floor
    _helpers.set_view("AgX", -0.5)          # let the highlights carry the image


register_preset("specular", apply)
