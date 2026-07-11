"""Pipeline step: the Cycles / EEVEE toggle (the one-click switch).

Robust to the EEVEE engine-id churn (4.2 shipped EEVEE-Next as
'BLENDER_EEVEE_NEXT'; later releases renamed it back to 'BLENDER_EEVEE') by
resolving the id against the render-engine enum at runtime.
"""
import bpy


def _eevee_engine_id():
    items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    ids = [i.identifier for i in items]
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        if candidate in ids:
            return candidate
    return "BLENDER_EEVEE"


def setup_engine(spec):
    from .presets.registry import OSL_MODES
    rspec = spec.get("render", {})
    engine = str(rspec.get("engine", "CYCLES")).upper()
    samples = int(rspec.get("samples", 128))
    denoise = bool(rspec.get("denoise", True))
    # OSL modes (crosshatch): derived from the MODE, not written into the spec,
    # so the flags self-heal on every mode switch instead of leaking. OSL forces
    # CPU, and denoising would smear the strokes (they ARE the signal).
    osl = str(rspec.get("mode", "")) in OSL_MODES
    scene = bpy.context.scene

    res = rspec.get("resolution", [1920, 1080])
    scene.render.resolution_x = int(res[0])
    scene.render.resolution_y = int(res[1])
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = bool(rspec.get("film_transparent", False))

    if engine == "EEVEE":
        scene.render.engine = _eevee_engine_id()
        scene.eevee.taa_render_samples = samples
        # EEVEE Next: enable raytracing so transmission/SSR resolve.
        if hasattr(scene.eevee, "use_raytracing"):
            scene.eevee.use_raytracing = True
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.shading_system = osl
        if osl:
            scene.cycles.device = "CPU"
            denoise = False
            scene.cycles.use_preview_denoising = False
            scene.cycles.preview_samples = 8   # emission-only: converges fast
        else:
            scene.cycles.use_preview_denoising = True
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
