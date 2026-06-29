"""Hatch - tonal shadow hatching. Continuous hatch lines (built in the view-ray
angular domain, so they converge in perspective) whose weight follows the shaded
tone: lit = blank paper, deeper shadow = denser, near-solid in the darkest pockets,
plus Line Art outlines. Keeps the sun (the shadows ARE the drawing). EEVEE-only
(Shader-to-RGB)."""
from .registry import register_preset
from . import _helpers
from .. import npr


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.show_ground()
    # Controlled light: a dim neutral (paper) world + a strong sun, so surfaces have
    # a real lit -> shadow tonal range for the hatch to read. The default bright
    # Nishita sky would flood everything to "lit" = no hatch.
    _helpers.set_neutral_world(1.0, 0.5)
    _helpers.set_sun_energy(4.0)
    _helpers.set_sun_softness(1.0)
    npr.set_flat_view()                  # Standard transform: crisp tone bands
    npr.apply_hatch(loaded, density=42.0, cross=False)
    npr.setup_line_art(radius=npr.default_line_radius(), color=(0.0, 0.0, 0.0),
                       crease_deg=70.0, thickness_factor=1.0)


register_preset("hatch", apply)
