"""Build the fast-open .blend scene cache for a bundle - headless.

    blender --background --python prepare_cache.py -- --bundle X --save-blend Y

Spawned DETACHED by Load View the moment extraction finishes, so the expensive
import + merge happens in the background while the user is still in Revit - by
the time they press Open View the cache is (usually) ready and the session
opens in seconds. Writes to a temp name and renames atomically, so a
half-written cache can never be opened; if the user beats the build, Open View
simply falls back to a fresh import exactly as before.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _args():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", required=True)
    p.add_argument("--save-blend", dest="save_blend", required=True)
    return p.parse_args(argv)


def _spec_mtime(bundle):
    try:
        from bir_contract.transport import bundle_spec_path, bundle_dir_of
        return os.path.getmtime(bundle_spec_path(bundle_dir_of(bundle)))
    except Exception:
        return None


def main():
    ns = _args()
    from blender.pipeline.run import import_scene
    from blender.pipeline import cache
    started_mtime = _spec_mtime(ns.bundle)
    try:
        print("Blendit: building scene cache (import + merge)...")
        import_scene(ns.bundle)
        # A NEWER Load View may have re-extracted while this build ran - its
        # own build supersedes this one; don't overwrite fresh with stale.
        if started_mtime is not None and _spec_mtime(ns.bundle) != started_mtime:
            print("Blendit: bundle changed during the build - discarding")
            return
        # .blend extension on the temp name too: save_as_mainfile appends one
        # otherwise (check_extension), which would break the rename.
        tmp = ns.save_blend + ".building.blend"
        cache.save_clean_blend(tmp)
        os.replace(tmp, ns.save_blend)      # atomic: never a half-written cache
        print("Blendit: scene cache ready -> %s" % ns.save_blend)
    finally:
        try:                                # clear the "scene building..." state
            os.remove(ns.save_blend + ".busy")
        except Exception:
            pass


if __name__ == "__main__":
    main()
