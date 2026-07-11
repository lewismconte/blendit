"""Data-driven render-mode registry.

A preset is a function `preset(loaded, spec)` that configures material overrides +
world + render specifics, reading the engine toggle from `spec`. Adding a mode is
just one more `register_preset(...)` call. Kept bpy-free so it can be listed
without Blender.
"""
_PRESETS = {}

# The stylised drawing/print modes (Grease Pencil Line Art present -> vector export
# possible, line-specific UI applies). SINGLE SOURCE OF TRUTH: both the headless
# renderer and the interactive session import this instead of keeping their own
# copies (which silently drifted). Kept here (bpy-free) so it can be listed without
# Blender; tests/ assert it stays a subset of bir_contract's RENDER_MODES.
LINE_MODES = ("linework", "pen", "sketch", "cel", "hatch", "crosshatch",
              "yellowtrace", "kraft", "blueprint", "diagram", "watercolor",
              "risograph")

# Modes whose materials use OSL Script nodes: Cycles-only, CPU device, and
# denoising must stay OFF (it smears the strokes). engine.py and the live
# session derive shading_system / device / denoise from this tuple instead of
# mutating the shared spec (which would leak into other modes).
OSL_MODES = ("crosshatch",)


def register_preset(name, fn):
    _PRESETS[name] = fn


def get_preset(name):
    # Fall back to realistic if an unknown mode slips through.
    return _PRESETS.get(name) or _PRESETS["realistic"]


def has_preset(name):
    return name in _PRESETS


def preset_names():
    return sorted(_PRESETS)
