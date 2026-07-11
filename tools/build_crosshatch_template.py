"""Build tam_hatch_template.blend for the Crosshatch render mode.

Run in GUI Blender (a window is REQUIRED - OSL Script-node socket creation
only exists as a GUI operator):

    blender --python tools/build_crosshatch_template.py

Produces blender/resources/hatch_tam/tam_hatch_template.blend containing one
datablock: material "BIR_Crosshatch" (fake-user) whose Script node was
compiled from tam_hatch.osl, with a UV Map node ("TamUV") linked into UVIn.
The pipeline appends this material at render time; headless Cycles then
compiles the EXTERNAL .osl source itself - no GUI needed after this step.

Re-run (and commit the result) whenever tam_hatch.osl's PARAMETER LIST
changes; body-only edits don't need a rebuild (EXTERNAL mode recompiles from
source at render time). The script hard-fails if the compiled sockets don't
match EXPECTED_SOCKETS - update that list together with the shader signature.

Startup scripts run in a restricted context, so the work is deferred to an
app timer; Cycles + shading_system must be enabled BEFORE the compile or the
operator's poll fails with "context is incorrect".
"""
import json
import os
import traceback

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_DIR = os.path.join(REPO, "blender", "resources", "hatch_tam")
OSL_PATH = os.path.join(RES_DIR, "tam_hatch.osl")
OUT_BLEND = os.path.join(RES_DIR, "tam_hatch_template.blend")

MATERIAL = "BIR_Crosshatch"
UV_LAYER = "TamUV"

EXPECTED_SOCKETS = [
    "UVIn", "ambient", "debug_lod", "fixed_tone", "kd", "light_is_sun",
    "light_pos", "sun_dir", "swap_uv", "tam_dir", "threshold", "tone_mode",
    "use_uv_socket", "uv_name", "uv_scale", "v_aspect",
]

# Shipping defaults; tam_dir and sun_dir are set per-scene by
# blender/pipeline/hatch_tam.py at apply time.
DEFAULTS = {
    "tone_mode": 0,
    "light_is_sun": 1,
    "ambient": 0.15,     # full shadow -> darkness 0.85 -> the dense TAM
                         # columns; 0.5 capped the range at mid "dashes"
    "kd": 1.1,
    "uv_scale": 0.5,     # TamUV is in world metres; tiles must span ~32-256
                         # SCREEN px for the mip system, so metres-wide tiles
    "v_aspect": 1.0,
    "use_uv_socket": 1,  # UVIn via UV Map node; getattribute reads zeros headless
    "swap_uv": 0,
    "threshold": 0,
    "debug_lod": 0,
    "tam_dir": "",
}


def compile_script_node(nt, script):
    """Compile an OSL script node so its sockets exist (needs a GUI window)."""
    win = bpy.context.window_manager.windows[0]
    area = win.screen.areas[0]
    old_type = area.type
    try:
        area.type = 'NODE_EDITOR'
        space = area.spaces.active
        space.tree_type = 'ShaderNodeTree'
        space.shader_type = 'OBJECT'
        space.pin = True
        space.node_tree = nt
        nt.nodes.active = script
        for n in nt.nodes:
            n.select = (n == script)
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(window=win, screen=win.screen,
                                       area=area, region=region,
                                       space_data=space):
            bpy.ops.node.shader_script_update()
    finally:
        area.type = old_type


def main():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.shading_system = True
    scene.cycles.device = 'CPU'

    # strip the startup scene so the template ships one material and nothing else
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds, bpy.data.images):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)

    mat = bpy.data.materials.new(MATERIAL)
    mat.use_fake_user = True
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new('ShaderNodeOutputMaterial')
    out.location = (600, 0)
    emis = nt.nodes.new('ShaderNodeEmission')
    emis.location = (400, 0)
    script = nt.nodes.new('ShaderNodeScript')
    script.location = (100, 0)
    script.mode = 'EXTERNAL'
    script.filepath = OSL_PATH
    compile_script_node(nt, script)

    got = sorted(s.name for s in script.inputs)
    if got != sorted(EXPECTED_SOCKETS):
        raise RuntimeError(
            "compiled sockets don't match tam_hatch.osl's expected signature:\n"
            "  got:      %r\n  expected: %r\n"
            "Update EXPECTED_SOCKETS together with the shader." %
            (got, sorted(EXPECTED_SOCKETS)))

    uvnode = nt.nodes.new('ShaderNodeUVMap')
    uvnode.location = (-150, -150)
    uvnode.uv_map = UV_LAYER
    nt.links.new(uvnode.outputs['UV'], script.inputs['UVIn'])
    nt.links.new(script.outputs['Col'], emis.inputs['Color'])
    nt.links.new(emis.outputs['Emission'], out.inputs['Surface'])

    for key, val in DEFAULTS.items():
        script.inputs[key].default_value = val

    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=True)
    print("TEMPLATE_BUILD_OK " + json.dumps(
        {"blend": OUT_BLEND, "material": MATERIAL, "sockets": got}))


def _deferred():
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("TEMPLATE_BUILD_FAILED")
    finally:
        win = bpy.context.window_manager.windows[0]
        with bpy.context.temp_override(window=win, screen=win.screen):
            bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_deferred, first_interval=1.5)
