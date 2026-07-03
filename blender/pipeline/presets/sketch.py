"""Sketch - hand-drawn look: flat paper fill + wobbly Line Art (GP noise) with
corner OVERSHOOT (lines overdrawn past their intersections, the classic
architectural-sketch tell) over a warm paper background. Renders under EEVEE."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()
    override_all(loaded, npr.make_flat_material((0.96, 0.95, 0.91), "BIR_Paper"))
    npr.set_world_flat((0.98, 0.97, 0.93), 1.0)
    npr.hide_ground()
    npr.setup_line_art(radius=npr.default_line_radius() * 1.2,
                       color=(0.13, 0.11, 0.10), crease_deg=60.0,
                       thickness_factor=1.0)
    npr.set_sketchiness(0.6)
    npr.set_line_overshoot(0.12)     # overdraw corners (the Overshoot slider)


register_preset("sketch", apply)
