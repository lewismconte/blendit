"""Pipeline step: the base photoreal look — view transform + exposure.

Applied before the per-mode preset so every mode inherits a good baseline.
Compositor passes (subtle bloom / vignette / AO) are a Phase 1 addition; the hook
is here.
"""
import bpy

# Base exposure is neutral now: each render-mode preset sets its own view transform
# + exposure (realistic/specular AgX-filmic, white/clay Standard so white stays
# white) via presets/_helpers.set_view, so this is just the pre-preset baseline.
_BASE_EXPOSURE = 0.0


def apply_look(spec):
    rspec = spec.get("render", {})
    view = bpy.context.scene.view_settings

    # AgX is the Blender 4.x default and the heart of the "filmic, not blown-out"
    # look. Guard the assignment in case a build lacks the transform.
    want = str(rspec.get("view_transform", "AgX"))
    try:
        view.view_transform = want
    except TypeError:
        view.view_transform = "Standard"

    view.exposure = float(rspec.get("exposure", 0.0)) + _BASE_EXPOSURE

    # TODO (Phase 1): compositor pass — subtle bloom, vignette, optional AO mix.
    # bpy.context.scene.use_nodes = True; build a small node graph here.
