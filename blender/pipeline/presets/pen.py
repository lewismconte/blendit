"""Pen - Rhino-style technical pen: flat white fill, clean black Line Art over a
white background. Renders under EEVEE (Line Art previews live)."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()
    override_all(loaded, npr.make_flat_material((1.0, 1.0, 1.0), "BIR_PenFill"))
    npr.set_world_flat((1.0, 1.0, 1.0), 1.0)
    npr.hide_ground()
    npr.setup_line_art(radius=npr.default_line_radius(), color=(0.0, 0.0, 0.0),
                       crease_deg=65.0, thickness_factor=1.0)


register_preset("pen", apply)
