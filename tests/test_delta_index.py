"""Live-sync delta bookkeeping - the parts that run without Revit (CPython).

Run: python tests/test_delta_index.py

The dirty-id extraction path needs the Revit API and is exercised live (the
established pattern for extraction code). What IS testable headless: the node
index seeds correctly from a bundle spec (multi-node elements grouped), and a
deleted-only patch resolves node names through the index and prunes it.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
for p in (_ROOT, os.path.join(_ROOT, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

from bir_extract import delta  # noqa: E402


def main():
    # --- index seeds from the committed fixture bundle -----------------------
    bundle = os.path.join(_HERE, "fixtures")
    index = delta.load_node_index(bundle)
    assert index.get("1") == ["Box_1"], index
    assert index.get("2") == ["Glass_1"], index
    print("load_node_index OK (%r)" % index)

    # --- multi-node elements group under one element id ----------------------
    fake = {"101": ["Walls_101", "Walls_101_1"], "55": ["Doors_55"]}

    # --- deleted-only patch: names come from the index; index prunes ---------
    meshes, removed = delta.build_patch(None, None, [], [101, 999], fake)
    assert meshes == []
    assert removed == ["Walls_101", "Walls_101_1"], removed
    assert "101" not in fake and fake.get("55") == ["Doors_55"], fake
    print("deleted-only patch OK (unknown id 999 is a clean no-op)")

    # --- empty flush is a no-op ----------------------------------------------
    meshes, removed = delta.build_patch(None, None, [], [], fake)
    assert meshes == [] and removed == []
    print("empty flush OK")

    print("DELTA INDEX OK")


main()
