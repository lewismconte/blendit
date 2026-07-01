"""Validate the live-session UI registers cleanly (catches PropertyGroup / operator
/ panel definition errors that _register_ui would otherwise swallow).

Run: blender --background --python tests/headless_register.py
"""
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import blender.interactive.live as live   # importable now (no main() on import)

# Mode-list single source of truth: the Blender preset registry must list EXACTLY
# the modes the contract declares (RENDER_MODES). Importing the presets package
# registers all of them; this fails loudly if the registry and the contract drift.
from blender.pipeline.presets import preset_names
from bir_contract.scene_spec import RENDER_MODES
assert set(preset_names()) == set(RENDER_MODES), (
    "preset registry %s != contract RENDER_MODES %s"
    % (sorted(preset_names()), sorted(RENDER_MODES)))
print("preset registry matches RENDER_MODES (%d modes): %s"
      % (len(RENDER_MODES), sorted(RENDER_MODES)))

# Register for real, letting any definition error raise.
import blender.interactive.clouds as clouds
for cls in clouds.CLOUD_CLASSES:                 # vendored atmosphere/cloud tool
    bpy.utils.register_class(cls)
for cls in live._CLASSES:
    bpy.utils.register_class(cls)
bpy.types.Scene.bir = bpy.props.PointerProperty(type=live.BIR_Settings)
bpy.types.Scene.bir_clouds = bpy.props.PointerProperty(type=clouds.BIR_CloudSettings)
print("registered:", ", ".join(c.__name__ for c in clouds.CLOUD_CLASSES + live._CLASSES))

# The operators must exist.
for op in ("regenerate_lines", "render_final", "open_captures",
           "render_image", "toggle_mode", "export_vector",
           "clouds_generate", "clouds_add_sky", "clouds_quality"):
    assert hasattr(bpy.ops.bir, op), "%s operator missing" % op

# Atmosphere settings: preset switch + a slider round-trip (exercises callbacks).
cl = bpy.context.scene.bir_clouds
cl.preset = "CUMULONIMBUS"
assert cl.density > 0.0 and cl.height_top > cl.height_base, "preset did not apply"
cl.coverage = 0.6
assert abs(cl.coverage - 0.6) < 1e-3
print("atmosphere settings OK (preset=%s, %d presets)"
      % (cl.preset, len(clouds.PRESETS)))

# Touch every new property (exercises types/limits + update callbacks safely).
st = bpy.context.scene.bir
st.projection = "ORTHO"
st.show_gizmos = True
st.clip_near = 0.1
st.clip_far = 5000.0
st.line_crease = 55.0
st.line_intersection = True
st.line_occlusion = True
st.line_thickness = 0.05
st.final_samples = 256
st.sun_softness = 5.0
st.gloss = 0.5
st.line_color = (0.1, 0.1, 0.4)
st.sun_use_datetime = True
st.sun_lat = 51.5
st.sun_lon = -0.13
st.sun_tz = 0.0
st.sun_month = 6
st.sun_day = 21
st.sun_time = 14.0
st.frame_view = True     # drives _update_sun_time -> sun_calc (safe with no scene sun)
st.aspect = "1:1"      # exercises _apply_aspect (sets render resolution)
st.projection = "TWO_POINT"   # camera controls: _update_camera -> _reapply_camera (no-op, no cam)
st.focal_length = 35.0
st.lens_shift = 0.2
assert st.projection == "TWO_POINT" and abs(st.lens_shift - 0.2) < 1e-3
st.projection = "ORTHO"
assert st.show_gizmos is True
assert abs(st.line_crease - 55.0) < 1e-3
assert bpy.context.scene.render.resolution_x == bpy.context.scene.render.resolution_y, \
    "1:1 aspect should square the resolution"
print("all new props set/readback OK")

# Materials list: collection + UIList + surface enum (the override UI).
assert hasattr(bpy.types, "BIR_UL_materials"), "materials UIList missing"
it = st.material_overrides.add()
it.mat_id = "mat_1"
it.name = "Brick, Common"
it.surface = "brick"
assert st.material_overrides[0].surface == "brick"
it.surface = "auto"   # exercises the update callback (no scene -> just persists/no-op)
print("materials list OK")
print("REGISTER OK")
