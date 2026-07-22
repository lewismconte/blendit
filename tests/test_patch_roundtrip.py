"""Live-sync patch envelope: write_patch/read_patch roundtrip (pure CPython).

Run: python tests/test_patch_roundtrip.py

Locks the spool protocol both sides depend on: the envelope fields survive a
roundtrip byte-exact, patches list in NUMERIC seq order, writes are atomic
(no half-written file is ever visible under a patch_*.json name), and
clear_patches removes exactly the spooled files.
"""
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
for p in (_ROOT, os.path.join(_ROOT, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

from bir_contract import transport  # noqa: E402
from bir_contract.transport import MeshData  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="blendit_patch_test_")
    try:
        bundle = os.path.join(tmp, "bundle")
        os.makedirs(bundle)
        spool = transport.patch_dir_of(bundle, create=True)
        assert os.path.isdir(spool) and spool.endswith(transport.PATCH_DIR)
        # bundle_ref as spec path resolves to the same spool
        assert transport.patch_dir_of(
            os.path.join(bundle, "scene_spec.json")) == spool
        print("patch_dir_of OK")

        # --- roundtrip ------------------------------------------------------
        meshes = [
            MeshData("Walls_101", [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                                   (10.0, 0.0, 8.0)],
                     [(0, 1, 2)], material_id="mat_7"),
            MeshData("Walls_101_1", [(0.0, 1.0, 0.0), (5.0, 1.0, 0.0),
                                     (5.0, 1.0, 8.0), (0.0, 1.0, 8.0)],
                     [(0, 1, 2), (0, 2, 3)], material_id="mat_9"),
        ]
        cam = {"position": [1.0, 2.0, 3.0]}
        path = transport.write_patch(spool, 1, meshes,
                                     ["Doors_55", "Doors_55_1"], camera=cam)
        assert os.path.isfile(path), path
        assert transport.patch_seq_of(path) == 1
        env = transport.read_patch(path)
        assert env["kind"] == transport.PATCH_KIND
        assert env["seq"] == 1
        assert env["removed"] == ["Doors_55", "Doors_55_1"]
        assert env["camera"] == cam
        assert len(env["updated"]) == 2
        u0 = env["updated"][0]
        assert u0["node"] == "Walls_101"
        assert u0["material_id"] == "mat_7"
        assert u0["vertices"] == [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0],
                                  [10.0, 0.0, 8.0]]
        assert u0["faces"] == [[0, 1, 2]]
        print("roundtrip OK")

        # dict-shaped meshes (the applier's own type) serialize identically
        transport.write_patch(spool, 2, [dict(u0)], [])
        env2 = transport.read_patch(transport.list_patches(spool)[-1])
        assert env2["updated"][0] == u0
        print("dict meshes OK")

        # --- ordering: numeric, not lexical ---------------------------------
        for seq in (10, 3):
            transport.write_patch(spool, seq, [], [])
        seqs = [transport.patch_seq_of(p) for p in transport.list_patches(spool)]
        assert seqs == [1, 2, 3, 10], seqs
        assert transport.next_patch_seq(spool) == 11
        print("seq ordering OK")

        # --- atomicity: a stray .tmp is invisible to the poller --------------
        stray = os.path.join(spool, "patch_000099.json.tmp")
        open(stray, "w").write("{half written")
        assert all(not p.endswith(".tmp") for p in transport.list_patches(spool))
        print("tmp invisible OK")

        # --- read_patch rejects non-patches ----------------------------------
        bogus = os.path.join(spool, "patch_000042.json")
        transport.write_json(bogus, {"kind": "something_else"})
        try:
            transport.read_patch(bogus)
            raise AssertionError("read_patch accepted a non-patch")
        except ValueError:
            pass
        print("kind check OK")

        # --- clear_patches removes patches + tmps, nothing else --------------
        keeper = os.path.join(spool, "notes.txt")
        open(keeper, "w").write("keep me")
        n = transport.clear_patches(spool)
        assert transport.list_patches(spool) == []
        assert not os.path.exists(stray)
        assert os.path.isfile(keeper)
        assert n >= 5, n
        print("clear_patches OK (%d removed)" % n)

        print("PATCH ROUNDTRIP OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


main()
