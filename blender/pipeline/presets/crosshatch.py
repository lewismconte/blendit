"""Crosshatch - authored Tonal Art Map hatching (Praun et al. 2001). Hand-drawn
stroke textures whose density follows the Lambert tone of the sun, with custom
mip selection so strokes keep constant SCREEN width at any distance, plus Line
Art outlines. Tone is orientation-only (no cast shadows - unlike `hatch`, which
draws the shadows). Cycles-only (OSL Script node), CPU; engine.py derives
shading_system/device/denoise from the mode so nothing leaks into the shared
spec. Four stroke styles: ink, brush, sketchy, charcoal."""
from .registry import register_preset
from . import _helpers
from .. import hatch_tam, npr


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "CYCLES"
    _helpers.disable_freestyle()
    npr.show_ground()
    # White paper world: lighting is analytic (in-shader), so the world only
    # paints the background pixels.
    _helpers.set_neutral_world(1.0, 1.0)
    npr.set_flat_view()                  # Standard transform: ink stays black
    hatch_tam.apply_crosshatch(loaded, style="ink", uv_scale=3.0,
                               ambient=0.5, threshold=False)
    npr.setup_line_art(radius=npr.default_line_radius(), color=(0.0, 0.0, 0.0),
                       crease_deg=70.0, thickness_factor=1.0)


register_preset("crosshatch", apply)
