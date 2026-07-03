"""Kraft / Brown Paper - black ink with WHITE accents on kraft: faces toward
the light pick up a white-pencil wash, shadow faces melt into the paper, black
Line Art over the top. Keeps the sun - the accents ARE the light. EEVEE-only
(Shader-to-RGB)."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all

_KRAFT = (0.30, 0.20, 0.12)          # the paper


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()
    # This preset OWNS its lighting (like hatch): the lit/shade threshold is
    # absolute, so a controlled sun beats whatever the model's sun study set -
    # a low winter sun would otherwise leave every face below the accent line.
    npr.set_world_flat(_KRAFT, 1.0)
    _helpers.set_sun_energy(4.0)
    _helpers.set_sun_softness(2.0)
    override_all(loaded, npr.make_two_tone_material(
        (0.26, 0.17, 0.10),          # shade: just under the paper tone
        (0.93, 0.91, 0.86),          # lit: the white-pencil accent
        threshold=0.33, name="BIR_Kraft"))
    npr.hide_ground()
    npr.setup_line_art(radius=npr.default_line_radius(),
                       color=(0.02, 0.015, 0.01), crease_deg=65.0,
                       thickness_factor=1.0)


register_preset("kraft", apply)
