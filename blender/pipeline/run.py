"""Pipeline orchestrator: bundle_ref -> rendered PNG.

Order follows the brief's run model:
    reset -> import -> look -> camera -> world -> preset -> engine -> render.
Base look/camera/world are applied first so every preset inherits a good baseline;
the preset then layers its mode-specific material/world/render overrides.
"""
import bpy

from .import_bundle import reset_scene, import_bundle
from .look import apply_look
from .camera import setup_camera
from .world import setup_world
from .ground import add_ground
from .engine import setup_engine
from . import presets  # noqa: F401  (registers all presets on import)
from .presets.registry import get_preset


def import_scene(bundle_ref, overrides=None):
    """Reset + import geometry only (no look/camera/world/preset). This is the
    state worth caching as a .blend: clean imported geometry, scaled to metres,
    merged by material, before any preset has touched materials. Returns
    (loaded, spec)."""
    reset_scene()
    loaded = import_bundle(bundle_ref)
    # Collapse the thousands of per-element objects into one-per-material: Line Art
    # and rendering are object-count-bound, so this is a 5-14x speedup with no
    # change in look. See merge.py.
    from .merge import merge_by_material
    merge_by_material(loaded)
    spec = loaded.spec
    # Where per-material surface overrides (the N-panel Materials list) are read from
    # - a Blender-side runtime annotation, next to the bundle, not a contract field.
    try:
        from bir_contract.transport import bundle_dir_of
        spec["_override_dir"] = bundle_dir_of(bundle_ref)
    except Exception:
        pass
    if overrides:
        _apply_overrides(spec, overrides)
    return loaded, spec


def prepare_scene(loaded, spec):
    """Everything after the geometry is in: look -> camera -> world -> ground ->
    preset -> engine. Re-runnable on a reloaded .blend (presets rebuild materials
    from the spec, so a cached scene re-materializes identically)."""
    scale = float(spec.get("units", {}).get("scale_to_meters", 1.0))
    apply_look(spec)
    setup_camera(spec, scale)        # frames to geometry BEFORE the ground exists
    setup_world(spec, scale)
    try:
        add_ground(spec)             # grounds the model; never fatal
    except Exception:
        pass

    mode = str(spec.get("render", {}).get("mode", "realistic"))
    get_preset(mode)(loaded, spec)

    setup_engine(spec)
    return loaded, spec


def build_scene(bundle_ref, overrides=None):
    """Set up the full scene (geometry, look, camera, world, materials, engine)
    WITHOUT rendering. Shared by the headless render and the interactive session.
    Returns (loaded, spec)."""
    loaded, spec = import_scene(bundle_ref, overrides)
    return prepare_scene(loaded, spec)


def run_pipeline(bundle_ref, out_path, overrides=None):
    loaded, spec = build_scene(bundle_ref, overrides)
    return _render(out_path, spec)


def run_vector_pipeline(bundle_ref, out_path, fmt, overrides=None):
    """Build the scene (in a line mode) and export the Line Art as SVG / PDF instead
    of rendering a raster. The mode must be a line mode (linework/pen/sketch/cel) so
    a Line Art GP exists to export."""
    build_scene(bundle_ref, overrides)
    from .vector_export import export_vector
    return export_vector(out_path, fmt)


def _render(out_path, spec):
    scene = bpy.context.scene
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    return out_path


def _apply_overrides(spec, overrides):
    r = spec.setdefault("render", {})
    if overrides.get("engine"):
        r["engine"] = str(overrides["engine"]).upper()
    if overrides.get("mode"):
        r["mode"] = str(overrides["mode"])
    if overrides.get("samples"):
        r["samples"] = int(overrides["samples"])
    if overrides.get("resolution"):
        r["resolution"] = list(overrides["resolution"])
    if overrides.get("denoise") is not None:
        r["denoise"] = bool(overrides["denoise"])
    if overrides.get("camera_type"):
        cam = spec.setdefault("camera", {})
        # A loaded 2D view (plan / section / elevation) carries its own orthographic
        # crop camera; the session's default 'perspective' must not clobber it.
        if str(cam.get("frame")) != "crop":
            cam["type"] = str(overrides["camera_type"])
    if overrides.get("two_point") is not None:
        spec.setdefault("camera", {})["two_point_perspective"] = bool(
            overrides["two_point"])
