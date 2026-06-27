"""Cel - anime-style toon shading: flat colour bands (Shader-to-RGB) + a Line Art
outline, keeping the sun/sky/ground. EEVEE-only (Shader-to-RGB)."""
from .registry import register_preset
from . import _helpers
from .. import npr


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()
    npr.show_ground()
    npr.apply_toon(loaded, shades=3)
    npr.setup_line_art(radius=npr.default_line_radius(), color=(0.04, 0.04, 0.05),
                       crease_deg=70.0, thickness_factor=1.0)


register_preset("cel", apply)
