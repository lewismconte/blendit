"""Per-view cache slots + the loaded-views list - PLAIN PYTHON (no Revit, no bpy).

    blender --background --python tests/test_view_slots.py   (or plain python)

The Revit-side cache logic is duck-typed and guarded, so fake doc/view objects
exercise it: slot layout, rename stability, fingerprint meta, list ordering,
the legacy single-slot fallback, per-slot staleness, and removal.
"""
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_LIB = os.path.join(_ROOT, "lib")
for _p in (_ROOT, _LIB):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bir_bootstrap  # noqa: E402
import bir_export  # noqa: E402

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print("  %-58s %s %s" % (name, "OK" if ok else "FAIL", detail))


class FakeView(object):
    def __init__(self, name, uid):
        self.Name = name
        self.UniqueId = uid


class FakeDoc(object):
    PathName = r"C:\projects\tower.rvt"
    Title = "tower"

    def __init__(self, views=None):
        self._views = views or {}

    def GetElement(self, uid):
        return self._views.get(uid)


def main():
    tmp = tempfile.mkdtemp(prefix="blendit_slots_")
    real_root = bir_bootstrap.cache_root
    bir_bootstrap.cache_root = lambda: tmp   # isolate the cache for the test
    try:
        plan = FakeView("Level 1", "uid-plan-001")
        three_d = FakeView("{3D}", "uid-3d-002")
        doc = FakeDoc({"uid-plan-001": plan})

        # --- slots: distinct per view, stable per view, rename-stable ----------
        d1 = bir_export.cache_paths(doc, plan)[0]
        d2 = bir_export.cache_paths(doc, three_d)[0]
        check("two views get two slots", d1 != d2)
        check("slots live under <doc>/views/", os.sep + "views" + os.sep in d1)
        check("same view resolves to the same slot",
              bir_export.cache_paths(doc, plan)[0] == d1)
        renamed = FakeView("Level 1 - RENAMED", "uid-plan-001")
        check("renaming a view keeps its slot",
              bir_export.cache_paths(doc, renamed)[0] == d1)

        # --- fingerprint meta + the loaded-views list --------------------------
        for view, cdir in ((plan, d1), (three_d, d2)):
            open(os.path.join(cdir, "scene_spec.json"), "w").write("{}")
            bir_export.save_fingerprint(doc, cdir, view)
        # distinct timestamps for the ordering test (minute resolution ties)
        for cdir, when in ((d1, "2026-07-06 09:00"), (d2, "2026-07-06 10:30")):
            p = os.path.join(cdir, "fingerprint.json")
            meta = json.load(open(p))
            meta["loaded_at"] = when
            json.dump(meta, open(p, "w"))

        slots = bir_export.loaded_views(doc)
        check("loaded_views lists both slots", len(slots) == 2, str(len(slots)))
        check("newest first", slots[0]["view_name"] == "{3D}",
              str([s["view_name"] for s in slots]))
        check("meta carries name + uid",
              slots[1]["view_name"] == "Level 1"
              and slots[1]["view_uid"] == "uid-plan-001")

        # --- per-slot staleness -------------------------------------------------
        check("existing view: freshness unknowable headless -> no warning",
              bir_export.slot_staleness(doc, slots[1]) is None)
        gone = bir_export.slot_staleness(doc, slots[0])   # {3D} not in FakeDoc
        check("deleted view reported", gone is not None and "no longer" in gone,
              str(gone))

        # --- legacy single-slot fallback ---------------------------------------
        fresh = FakeView("North Elevation", "uid-elev-003")
        root = bir_bootstrap.cache_dir_for(bir_bootstrap.doc_cache_key(doc))
        open(os.path.join(root, "scene_spec.json"), "w").write("{}")
        bref, _blend = bir_export.cached_bundle(doc, fresh)   # slot empty
        check("legacy per-doc bundle found when the view slot is empty",
              bref == os.path.join(root, "scene_spec.json"), str(bref))
        bref2, _ = bir_export.cached_bundle(doc, plan)        # slot has a bundle
        check("a filled view slot wins over the legacy bundle",
              bref2 == os.path.join(d1, "scene_spec.json"), str(bref2))

        # --- removal ------------------------------------------------------------
        check("remove_slot deletes the slot",
              bir_export.remove_slot(slots[0]) and not os.path.isdir(d2))
        check("the other slot survives", os.path.isdir(d1))
    finally:
        bir_bootstrap.cache_root = real_root
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in CHECKS if not ok]
    print("SLOTS: %d checks, %d failed%s"
          % (len(CHECKS), len(failed), (" -> " + ", ".join(failed)) if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
