"""End-to-end validation of merge-by-material through the REAL pipeline:
import_scene (now merges) -> material assignment -> .blend cache save/reopen
(reconstructs merged mapping) -> render. On the lighter cached model.

Run: blender --background --python tests/headless_merge_pipeline.py
"""
import os
import sys
import time
import tempfile

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Dev/perf tool: runs against a real cached model (heavy, many materials) where the
# 2-object fixture wouldn't exercise merge meaningfully. Point it at any cached
# bundle via BLENDIT_TEST_BUNDLE, else the default local cache slot; skip cleanly
# when neither exists so a fresh clone doesn't fail.
def _default_cached_bundle():
    """First model cache slot under %LOCALAPPDATA%\\blendit\\cache, if any."""
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "blendit", "cache")
    try:
        for name in sorted(os.listdir(root)):
            cand = os.path.join(root, name, "scene_spec.json")
            if os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return ""


BUNDLE = os.environ.get("BLENDIT_TEST_BUNDLE") or _default_cached_bundle()

if not BUNDLE or not os.path.isfile(BUNDLE):
    print("SKIP headless_merge_pipeline: no local model cache "
          "(set BLENDIT_TEST_BUNDLE to a scene_spec.json to run the heavy-model test).")
    sys.exit(0)


def _meshes():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def main():
    from blender.pipeline.run import import_scene, prepare_scene, _apply_overrides
    from blender.pipeline import cache as bir_cache, merge

    # --- fresh-import path (now merges by material) ---
    t0 = time.time()
    loaded, spec = import_scene(BUNDLE, overrides={"camera_type": "perspective",
                                                   "mode": "realistic", "engine": "EEVEE"})
    n = len(_meshes())
    print("import + merge: %.1fs  ->  %d mesh objects" % (time.time() - t0, n))
    assert n < 200, "merge didn't collapse object count (%d)" % n
    assert loaded.node_to_object, "no node_to_object after merge"
    assert all(k.startswith("BIR_Mat_") for k in loaded.node_to_object), \
        "merged keys not BIR_Mat_*: %s" % list(loaded.node_to_object)[:3]

    # cache the clean (merged, pre-preset) scene, like live.py does
    blend = os.path.join(tempfile.mkdtemp(prefix="bir_merge_"), "scene.blend")
    bir_cache.save_clean_blend(blend)
    print("cached merged .blend: %d bytes" % os.path.getsize(blend))

    prepare_scene(loaded, spec)            # realistic -> per-material PBR
    assigned = sum(1 for o in loaded.node_to_object.values() if len(o.data.materials) >= 1)
    print("realistic: %d/%d merged objects have a material"
          % (assigned, len(loaded.node_to_object)))
    assert assigned == len(loaded.node_to_object), "some merged objects got no material"

    # --- reopen path: open the cached .blend, rebuild loaded from merged names ---
    bir_cache.open_blend(blend)
    loaded2, spec2 = bir_cache.loaded_from_blend(BUNDLE)
    assert loaded2.node_to_object, "reopen: empty node_to_object"
    assert all(k.startswith("BIR_Mat_") for k in loaded2.node_to_object), \
        "reopen keys not merged"
    # element->material map must be reconstructed from names
    elems = {e["node"]: e for e in spec2.get("geometry", {}).get("elements", [])}
    assert elems, "reopen: no reconstructed elements"
    sample = next(iter(loaded2.node_to_object))
    assert elems.get(sample, {}).get("material_id") == merge.material_id_from_name(sample)
    print("reopen: %d merged objects, material map reconstructed from names"
          % len(loaded2.node_to_object))

    _apply_overrides(spec2, {"camera_type": "perspective", "mode": "linework",
                             "engine": "EEVEE"})
    t0 = time.time()
    prepare_scene(loaded2, spec2)          # linework on the reopened merged scene
    print("prepare linework on reopened merged scene: %.1fs" % (time.time() - t0))

    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 480, 270
    sc.render.image_settings.file_format = "PNG"
    out = os.path.join(_HERE, "_merge_pipeline.png")
    sc.render.filepath = out
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print("render linework (merged, reopened): %.1fs -> %d bytes"
          % (time.time() - t0, os.path.getsize(out) if os.path.isfile(out) else 0))
    assert os.path.isfile(out) and os.path.getsize(out) > 2000
    print("ALL OK")


main()
