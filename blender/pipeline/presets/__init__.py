"""Render-mode preset registry (the data-driven §9 modes).

Importing this package registers all nine modes via their modules: four lit/clay
(realistic, white, shadow, specular) plus five NPR (linework, pen, sketch, cel,
hatch). Adding a mode later = a new module that calls `register_preset(...)`,
imported here.
"""
from .registry import (  # noqa: F401
    register_preset, get_preset, has_preset, preset_names,
)

# Import the concrete presets for their registration side effects.
from . import realistic  # noqa: F401
from . import white      # noqa: F401
from . import shadow     # noqa: F401
from . import linework   # noqa: F401
from . import specular   # noqa: F401
from . import pen        # noqa: F401  (NPR: Rhino-style technical pen)
from . import sketch     # noqa: F401  (NPR: hand-drawn sketch)
from . import cel        # noqa: F401  (NPR: anime cel shading)
from . import hatch      # noqa: F401  (NPR: tonal shadow hatching)
