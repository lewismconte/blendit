"""glTF transport - Revit side.

A self-contained, pure-Python glTF 2.0 writer. No native deps, IronPython-2.7
safe (no f-strings, no annotations, no dataclasses). Takes tessellated MeshData
(Revit Z-up, source units = feet) + the SceneSpec materials and emits a single
binary `scene.glb` plus the sidecar `scene_spec.json`.

WHY .glb (binary) and not embedded .gltf: the geometry buffer ships as a raw
binary chunk appended to the file - no base64. base64 inflates the buffer ~33%
and forces a decode of one giant string on BOTH sides (it was the bulk of the
~100 s import on a 14k-element model). The binary chunk is smaller and Blender's
importer reads it directly. Same "gltf" transport name; only the container and
the geometry.uri (scene.glb) change. The contract is unchanged.

Packing is batched through `array.array` (one pack per attribute per mesh)
instead of millions of per-component `struct.pack` calls - the other half of the
export cost on big models.

AXIS: this is THE one place Revit Z-up is converted to glTF-native Y-up. Blender's
glTF importer (default "+Y up") converts back to Blender Z-up on the way in, so a
box stays upright and unrotated.
"""
import array
import json
import os
import shutil
import struct
import sys

from bir_contract.transport import Exporter, write_scene_spec, register_exporter

# glTF constant enums
_FLOAT = 5126
_UNSIGNED_INT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4

# GLB container magic / chunk-type tags (little-endian uint32).
_GLB_MAGIC = 0x46546C67   # 'glTF'
_GLB_VERSION = 2
_CHUNK_JSON = 0x4E4F534A  # 'JSON'
_CHUNK_BIN = 0x004E4942   # 'BIN\0'

_LITTLE = sys.byteorder == "little"  # glTF requires LE; Windows is always LE


def _array_bytes(a):
    # array -> bytes. tobytes() on CPython 3 (tests); tostring() on IronPython 2.7.
    if hasattr(a, "tobytes"):
        return a.tobytes()
    return a.tostring()


def _pack_floats(values):
    """Pack a flat list of floats to little-endian f32 bytes in one shot."""
    a = array.array("f", values)
    if not _LITTLE:
        a.byteswap()
    return _array_bytes(a)


def _pack_uints(values):
    """Pack a flat list of indices to little-endian u32 bytes in one shot."""
    a = array.array("I", values)
    if a.itemsize != 4:  # 'I' is 4 bytes on Windows; guard the exotic case
        return struct.pack("<%dI" % len(values), *values)
    if not _LITTLE:
        a.byteswap()
    return _array_bytes(a)


def _pad4(blob):
    # glTF requires 4-byte alignment between bufferViews.
    while len(blob) % 4 != 0:
        blob.append(0)


class GltfExporter(Exporter):
    name = "gltf"

    def export(self, spec_dict, meshes, out_dir):
        gltf, blob = self._build_gltf(meshes, spec_dict.get("materials", []))
        # GLB: the single buffer IS the BIN chunk - no uri, no base64.
        gltf["buffers"] = [{"byteLength": len(blob)}]
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        glb = self._assemble_glb(gltf, blob)
        f = open(os.path.join(out_dir, "scene.glb"), "wb")
        try:
            f.write(glb)
        finally:
            f.close()
        spec_dict.setdefault("geometry", {})
        spec_dict["geometry"]["transport"] = "gltf"
        spec_dict["geometry"]["uri"] = "scene.glb"
        self._copy_texture_maps(spec_dict, out_dir)
        # write_scene_spec emits UTF-8 (ensure_ascii=False) so a Revit name with a
        # non-ASCII char can't crash IronPython's json encoder - see transport.py.
        return write_scene_spec(out_dir, spec_dict)

    def _copy_texture_maps(self, spec_dict, out_dir):
        """Bundle the texture files: every material map carrying an absolute
        `source_path` (bir_extract/appearance.py) is copied into `textures/`
        and rewritten to a bundle-relative `uri`. Maps whose file is missing
        are dropped, so the Blender side never chases dead paths. Copies are
        deduped by source path (many Revit materials share one bitmap)."""
        copied = {}   # source path -> uri
        tex_dir = os.path.join(out_dir, "textures")
        # The exporter owns textures/: start clean so re-exports into the same
        # cache dir don't accumulate suffixed copies of every bitmap.
        if os.path.isdir(tex_dir):
            shutil.rmtree(tex_dir, ignore_errors=True)
        for rec in spec_dict.get("materials", []) or []:
            maps = rec.get("maps")
            if not maps:
                continue
            for slot in list(maps.keys()):
                entry = maps[slot] or {}
                src = entry.pop("source_path", None)
                entry.pop("uri", None)    # stale uris never survive an export
                uri = copied.get(src)
                if uri is None and src and os.path.isfile(src):
                    try:
                        if not os.path.isdir(tex_dir):
                            os.makedirs(tex_dir)
                        name = self._unique_name(tex_dir, os.path.basename(src))
                        shutil.copyfile(src, os.path.join(tex_dir, name))
                        uri = "textures/" + name
                        copied[src] = uri
                    except Exception:
                        uri = None
                if uri:
                    entry["uri"] = uri
                    maps[slot] = entry
                else:
                    del maps[slot]
            if not maps:
                rec["maps"] = None

    @staticmethod
    def _unique_name(tex_dir, name):
        """Different source files can share a basename; suffix until free."""
        if not os.path.exists(os.path.join(tex_dir, name)):
            return name
        stem, ext = os.path.splitext(name)
        i = 2
        while os.path.exists(os.path.join(tex_dir, "%s_%d%s" % (stem, i, ext))):
            i += 1
        return "%s_%d%s" % (stem, i, ext)

    def _assemble_glb(self, gltf, blob):
        """Wrap the glTF JSON + binary blob in the GLB container."""
        # ensure_ascii=False: never ask json to ascii-escape. IronPython's ascii
        # encoder decodes any high byte in a Revit name (material/category with a
        # non-ASCII char) through the system code page and dies; emitting UTF-8
        # skips that. glTF's JSON chunk is UTF-8 by spec, so this is also correct.
        json_bytes = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False)
        if hasattr(json_bytes, "encode"):
            json_bytes = json_bytes.encode("utf-8")
        # JSON chunk padded with spaces, BIN chunk with zeros; each multiple of 4.
        json_pad = (4 - (len(json_bytes) % 4)) % 4
        json_bytes = json_bytes + (b" " * json_pad)
        bin_pad = (4 - (len(blob) % 4)) % 4
        bin_bytes = bytes(blob) + (b"\x00" * bin_pad)

        total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
        out = bytearray()
        out += struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total)
        out += struct.pack("<II", len(json_bytes), _CHUNK_JSON)
        out += json_bytes
        out += struct.pack("<II", len(bin_bytes), _CHUNK_BIN)
        out += bin_bytes
        return bytes(out)

    def _build_gltf(self, meshes, materials):
        blob = bytearray()
        accessors = []
        buffer_views = []
        gltf_meshes = []
        nodes = []
        node_indices = []

        mat_index = self._build_materials(materials)

        for mesh in meshes:
            verts = mesh.vertices
            if not verts:
                continue
            primitive = {"mode": _TRIANGLES, "attributes": {}}

            # --- POSITION (Y-up; flatten + min/max in one pass, pack once) ---
            flat = []
            ap = flat.append
            x0, y0, z0 = verts[0][0], verts[0][2], -verts[0][1]
            vmin = [x0, y0, z0]
            vmax = [x0, y0, z0]
            for v in verts:
                x = v[0]; y = v[2]; z = -v[1]   # zup -> yup inline
                ap(x); ap(y); ap(z)
                if x < vmin[0]:
                    vmin[0] = x
                elif x > vmax[0]:
                    vmax[0] = x
                if y < vmin[1]:
                    vmin[1] = y
                elif y > vmax[1]:
                    vmax[1] = y
                if z < vmin[2]:
                    vmin[2] = z
                elif z > vmax[2]:
                    vmax[2] = z
            pos_offset = len(blob)
            blob.extend(_pack_floats(flat))
            buffer_views.append({
                "buffer": 0, "byteOffset": pos_offset,
                "byteLength": len(blob) - pos_offset, "target": _ARRAY_BUFFER,
            })
            accessors.append({
                "bufferView": len(buffer_views) - 1, "componentType": _FLOAT,
                "count": len(verts), "type": "VEC3", "min": vmin, "max": vmax,
            })
            primitive["attributes"]["POSITION"] = len(accessors) - 1
            _pad4(blob)

            # --- NORMAL (optional; converted to Y-up) ---
            if mesh.normals:
                nflat = []
                na = nflat.append
                for n in mesh.normals:
                    na(n[0]); na(n[2]); na(-n[1])
                nrm_offset = len(blob)
                blob.extend(_pack_floats(nflat))
                buffer_views.append({
                    "buffer": 0, "byteOffset": nrm_offset,
                    "byteLength": len(blob) - nrm_offset, "target": _ARRAY_BUFFER,
                })
                accessors.append({
                    "bufferView": len(buffer_views) - 1, "componentType": _FLOAT,
                    "count": len(mesh.normals), "type": "VEC3",
                })
                primitive["attributes"]["NORMAL"] = len(accessors) - 1
                _pad4(blob)

            # --- indices (SCALAR uint32) ---
            iflat = []
            ia = iflat.append
            for face in mesh.faces:
                ia(face[0]); ia(face[1]); ia(face[2])
            idx_offset = len(blob)
            blob.extend(_pack_uints(iflat))
            buffer_views.append({
                "buffer": 0, "byteOffset": idx_offset,
                "byteLength": len(blob) - idx_offset,
                "target": _ELEMENT_ARRAY_BUFFER,
            })
            accessors.append({
                "bufferView": len(buffer_views) - 1,
                "componentType": _UNSIGNED_INT, "count": len(iflat), "type": "SCALAR",
            })
            primitive["indices"] = len(accessors) - 1
            _pad4(blob)

            if mesh.material_id is not None and mesh.material_id in mat_index:
                primitive["material"] = mat_index[mesh.material_id]

            gltf_meshes.append({"primitives": [primitive]})
            nodes.append({"name": mesh.node, "mesh": len(gltf_meshes) - 1})
            node_indices.append(len(nodes) - 1)

        gltf = {
            "asset": {"version": "2.0", "generator": "Blendit"},
            "scene": 0,
            "scenes": [{"nodes": node_indices}],
            "nodes": nodes,
            "meshes": gltf_meshes,
            "accessors": accessors,
            "bufferViews": buffer_views,
        }
        if materials:
            gltf["materials"] = self._gltf_materials(materials)
        return gltf, blob

    def _build_materials(self, materials):
        # {SceneSpec material id -> glTF material index}, preserving list order.
        index = {}
        i = 0
        for rec in materials:
            index[rec["id"]] = i
            i += 1
        return index

    def _gltf_materials(self, materials):
        out = []
        for rec in materials:
            base = rec.get("base_color", [0.8, 0.8, 0.8])
            transparency = float(rec.get("transparency", 0.0))
            alpha = 1.0 - transparency
            pbr = {
                "baseColorFactor": [float(base[0]), float(base[1]),
                                    float(base[2]), alpha],
                "metallicFactor": float(rec.get("metallic", 0.0)),
                "roughnessFactor": float(rec.get("roughness", 0.5)),
            }
            mat = {"name": rec.get("name", rec["id"]),
                   "pbrMetallicRoughness": pbr}
            if transparency > 0.0:
                mat["alphaMode"] = "BLEND"
            emissive = rec.get("emissive")
            if emissive:
                mat["emissiveFactor"] = [float(emissive[0]), float(emissive[1]),
                                         float(emissive[2])]
            out.append(mat)
        return out


register_exporter(GltfExporter())
