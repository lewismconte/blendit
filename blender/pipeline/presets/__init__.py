"""Render-mode preset registry (the data-driven §9 modes).

Importing this package registers all twelve modes via their modules: four
lit/clay (realistic, white, shadow, specular) plus eight NPR (linework, pen,
sketch, cel, hatch, yellowtrace, kraft, blueprint). Adding a mode later = a
new module that calls `register_preset(...)`, imported here.
"""
from .registry import (  # noqa: F401
    register_preset, get_preset, has_preset, preset_names,
)

# Import the concrete presets for their registration side effects.
from . import realistic    # noqa: F401
from . import white        # noqa: F401
from . import shadow       # noqa: F401
from . import linework     # noqa: F401
from . import specular     # noqa: F401
from . import pen          # noqa: F401  (NPR: Rhino-style technical pen)
from . import sketch       # noqa: F401  (NPR: hand-drawn sketch)
from . import cel          # noqa: F401  (NPR: anime cel shading)
from . import hatch        # noqa: F401  (NPR: tonal shadow hatching)
from . import yellowtrace  # noqa: F401  (NPR: sketch on yellow trace paper)
from . import kraft        # noqa: F401  (NPR: white accents on brown paper)
from . import blueprint    # noqa: F401  (NPR: white lines on cyanotype blue)
