"""Linework - Line Art outlines over a light clay fill (lines + soft shading).
Renders under EEVEE so the lines preview live."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import make_clay_material, override_all


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.show_ground()
    override_all(loaded, make_clay_material("LineClay", value=0.9, roughness=0.8))
    npr.setup_line_art(radius=npr.default_line_radius(), color=(0.05, 0.05, 0.05),
                       crease_deg=70.0, thickness_factor=1.0)


register_preset("linework", apply)
