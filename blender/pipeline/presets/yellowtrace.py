"""Yellowtrace - the concept sketch on yellow trace paper (butter paper):
warm canary ground with crisp BLACK ink over it. The classic tracing-paper
overlay - clean black linework, only a whisper of hand wobble. Renders under EEVEE."""
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
    npr.setup_line_art(radius=npr.default_line_radius() * 1.05,
                       color=(0.0, 0.0, 0.0), crease_deg=62.0,
                       thickness_factor=1.0)
    npr.set_sketchiness(0.12)        # just a whisper of wobble - keep it crisp
    npr.set_line_overshoot(0.04)     # barely any overdraw


register_preset("yellowtrace", apply)
