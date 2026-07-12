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
    # uv_scale: TAM tiles per METRE. The mip system works while one tile spans
    # ~32-256 SCREEN px, so at whole-building framing (~35 px/m) tiles must be
    # metres wide; 3.0 put tiles at ~12 px = sub-pixel strokes aliasing to
    # flat grey (the "dense noise" failure).
    # ambient floors the tone: 0.15 lets full shadow reach the DENSE
    # cross-hatch columns (darkness 0.85 -> column ~5, the classic look).
    # 0.5 - ported by mistake from the procedural hatch's tuning - capped
    # darkness at 0.5, so nothing ever drew past mid "sparse dashes".
    hatch_tam.apply_crosshatch(loaded, style="ink", uv_scale=0.5,
                               ambient=0.15, threshold=False)
    npr.setup_line_art(radius=npr.default_line_radius(), color=(0.0, 0.0, 0.0),
                       crease_deg=70.0, thickness_factor=1.0)


register_preset("crosshatch", apply)
