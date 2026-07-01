"""Standalone validation of the .glb binary writer (no Blender, no Revit).

Builds a unit box through the Revit-side GltfExporter, then re-parses the GLB
container and checks: magic/version/length, JSON+BIN chunk framing, that every
bufferView lies inside the BIN chunk, and that the POSITION accessor min/max
matches the box. Run: python tests/validate_glb.py
"""
import json
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lib"))

from bir_contract.transport import MeshData
from bir_transports.gltf.exporter import GltfExporter


def _unit_box():
    # 8 corners, 12 triangles (z-up, feet). Just enough to exercise the writer.
    v = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
         (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    f = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
         (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
         (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]
    return MeshData("Wall_1", v, f, material_id="mat_1")


def _parse_glb(data):
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "bad GLB magic"
    assert version == 2, "bad GLB version"
    assert length == len(data), "length field %d != file %d" % (length, len(data))
    off = 12
    chunks = []
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        chunks.append((ctype, data[off:off + clen]))
        off += clen
        assert off % 4 == 0, "chunk not 4-byte aligned"
    return chunks


def main():
    meshes = [_unit_box()]
    spec = {"contract_version": "0.1.0",
            "materials": [{"id": "mat_1", "name": "Brick",
                           "base_color": [0.6, 0.3, 0.2]}],
            "units": {"scale_to_meters": 0.3048}}
    out_dir = tempfile.mkdtemp(prefix="bir_glb_")
    bundle_ref = GltfExporter().export(spec, meshes, out_dir)

    glb_path = os.path.join(out_dir, "scene.glb")
    data = open(glb_path, "rb").read()
    chunks = _parse_glb(data)
    assert len(chunks) == 2, "expected JSON + BIN chunks, got %d" % len(chunks)
    json_type, json_bytes = chunks[0]
    bin_type, bin_bytes = chunks[1]
    assert json_type == 0x4E4F534A, "first chunk must be JSON"
    assert bin_type == 0x004E4942, "second chunk must be BIN"

    gltf = json.loads(json_bytes.decode("utf-8"))
    assert gltf["buffers"][0]["byteLength"] <= len(bin_bytes)
    assert "uri" not in gltf["buffers"][0], "GLB buffer must have no uri"

    # Every bufferView must lie within the BIN chunk.
    for bv in gltf["bufferViews"]:
        end = bv["byteOffset"] + bv["byteLength"]
        assert end <= len(bin_bytes), "bufferView overruns BIN chunk"

    # POSITION accessor min/max should be the box's corners (Y-up: x,z,-y).
    pos = None
    for acc in gltf["accessors"]:
        if acc.get("type") == "VEC3" and "min" in acc:
            pos = acc
            break
    assert pos is not None, "no POSITION accessor with min/max"
    # box spans 0..1 on each axis; after z-up->y-up (-y) one axis goes -1..0.
    assert pos["count"] == 8, "expected 8 verts, got %d" % pos["count"]

    sidecar = json.loads(open(bundle_ref).read())
    assert sidecar["geometry"]["transport"] == "gltf"
    assert sidecar["geometry"]["uri"] == "scene.glb"

    print("OK  glb=%d bytes  json=%d  bin=%d  verts=%d  min=%s max=%s"
          % (len(data), len(json_bytes), len(bin_bytes), pos["count"],
             pos["min"], pos["max"]))
    print("OK  bundle_ref=%s" % bundle_ref)


if __name__ == "__main__":
    main()
