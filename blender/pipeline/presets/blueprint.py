"""Blueprint - white line work on cyanotype blue, the classic reproduction
print. Faces fill in nearly the paper blue (a whisper lighter, so overlapping
massing still separates); the drawing is carried by the white lines. EEVEE."""
from .registry import register_preset
from . import _helpers
from .. import npr
from ..materials import override_all

_BLUE = (0.012, 0.045, 0.16)         # the paper


def apply(loaded, spec):
    spec.setdefault("render", {})["engine"] = "EEVEE"
    _helpers.disable_freestyle()
    npr.set_flat_view()
    override_all(loaded, npr.make_flat_material((0.020, 0.060, 0.19),
                                                "BIR_BlueprintFill"))
    npr.set_world_flat(_BLUE, 1.0)
    npr.hide_ground()
    npr.setup_line_art(radius=npr.default_line_radius() * 0.9,
                       color=(0.92, 0.96, 1.0), crease_deg=65.0,
                       thickness_factor=1.0)


register_preset("blueprint", apply)
