"""Yellowtrace - the concept sketch on yellow trace paper (butter paper):
warm canary ground, loose dark-sepia lines with wobble AND corner overshoot.
The overlay architects actually sketch on. Renders under EEVEE."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()
    # Fill a touch deeper than the paper so massing separates without shading.
    override_all(loaded, npr.make_flat_material((0.96, 0.77, 0.36), "BIR_Trace"))
    npr.set_world_flat((1.0, 0.84, 0.44), 1.0)
    npr.hide_ground()
    npr.setup_line_art(radius=npr.default_line_radius() * 1.1,
                       color=(0.16, 0.10, 0.05), crease_deg=62.0,
                       thickness_factor=1.0)
    npr.set_sketchiness(0.5)         # looser than Sketch's paper drawing
    npr.set_line_overshoot(0.16)     # trace sketches overdraw generously


register_preset("yellowtrace", apply)
