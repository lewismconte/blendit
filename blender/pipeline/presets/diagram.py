"""Diagram - the competition-board poster look: the massing as one bold, flat
colour-blocked shape under a heavy black outline, on white paper with a soft
contact shadow. Reads like an architectural pictogram (the OMA / BIG diagram
board). A single flat emission fill stays graphic on any object count (per-object
rainbow would turn a detailed model to noise). Renders under EEVEE."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all

# A confident poster hue - distinct from blueprint (blue), yellowtrace (yellow) and
# kraft (brown). Persimmon/coral reads friendly and modern on a contact sheet.
_INK = (0.90, 0.35, 0.25)


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()                       # Standard transform -> the flat colour is true
    # Emission fill: ignores the light, so the mass stays a flat graphic block while
    # only the ground reads the sun -> a clean poster shape with a soft drop shadow.
    override_all(loaded, npr.make_flat_material(_INK, "BIR_Diagram"))
    npr.show_ground()
    _helpers.set_neutral_world(0.85, 1.0)     # bright even fill -> no gradients on the fill
    _helpers.set_sun_energy(2.2)              # just enough for a soft contact shadow
    _helpers.set_sun_softness(3.5)            # soft-edged shadow pool
    _helpers.set_ground_tone(1.0)             # pure white paper
    # Heavy silhouette outline - the poster tell. High crease so only the big edges draw.
    npr.setup_line_art(radius=npr.default_line_radius() * 2.2,
                       color=(0.0, 0.0, 0.0), crease_deg=78.0,
                       thickness_factor=1.0)


register_preset("diagram", apply)
