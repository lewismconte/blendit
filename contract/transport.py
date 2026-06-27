"""Blendit - transport layer (the seam).

Exporter : Revit side, IronPython 2.7 -> writes a Bundle
Importer : Blender side, CPython 3     -> reads a Bundle into Blender

KEEP THIS MODULE IRONPYTHON-2.7 SAFE: no f-strings, no type annotations in
signatures, no dataclasses. Type hints are in comments. The on-disk Bundle
(entry point scene_spec.json) is the cross-process contract.
"""
import json
import os

CONTRACT_VERSION = "0.1.0"
SCENE_SPEC_FILENAME = "scene_spec.json"


# A Bundle is what a transport produces/consumes. For file-based transports it is
# a directory whose entry point is scene_spec.json:
#   my_bundle/
#     scene_spec.json   # conforms to scene_spec.schema.json (Appendix A)
#     scene.glb         # geometry payload (binary glTF)
#     assets/           # optional HDRIs / textures
# A "bundle_ref" is the path to the dir OR directly to scene_spec.json. For a
# future in-memory transport (websocket) a bundle_ref may be an object/URL -
# treat it as opaque; only the matching transport interprets it.


def bundle_spec_path(bundle_dir):
    # (str) -> str
    return os.path.join(bundle_dir, SCENE_SPEC_FILENAME)


def write_scene_spec(bundle_dir, spec_dict):
    # (str, dict) -> str   ; returns bundle_ref (path to scene_spec.json)
    if not os.path.isdir(bundle_dir):
        os.makedirs(bundle_dir)
    path = bundle_spec_path(bundle_dir)
    f = open(path, "w")
    try:
        json.dump(spec_dict, f, indent=2)
    finally:
        f.close()
    return path


def read_scene_spec(bundle_ref):
    # (str) -> dict
    if bundle_ref.endswith(".json") and os.path.isfile(bundle_ref):
        path = bundle_ref
    else:
        path = bundle_spec_path(bundle_ref)
    f = open(path)
    try:
        return json.load(f)
    finally:
        f.close()


def bundle_dir_of(bundle_ref):
    # (str) -> str
    return os.path.dirname(bundle_ref) if bundle_ref.endswith(".json") else bundle_ref


class MeshData(object):
    """What Revit extraction hands to a file-based exporter. Pure container so
    'extract from Revit' (RevitAPI) is decoupled from 'write payload' (testable).
    One per Revit element; `node` matches a SceneSpec Element.node."""

    def __init__(self, node, vertices, faces,
                 normals=None, uvs=None, material_id=None):
        # node        : str             stable key; == Element.node
        # vertices    : list[(x,y,z)]   source units (feet), Z-up
        # faces       : list[(i,j,k)]   triangles (indices into vertices)
        # normals     : list[(x,y,z)] | None
        # uvs         : list[(u,v)]    | None
        # material_id : str | None      == a SceneSpec material id
        self.node = node
        self.vertices = vertices
        self.faces = faces
        self.normals = normals
        self.uvs = uvs
        self.material_id = material_id


class Exporter(object):
    """Revit side. Writes a Bundle from a SceneSpec dict + tessellated MeshData."""
    name = None  # == SceneSpec.geometry.transport, e.g. "gltf"

    def export(self, spec_dict, meshes, out_dir):
        # (dict, list[MeshData], str) -> str (bundle_ref)
        # Must: write geometry payload, set spec_dict["geometry"]["transport"]
        # and ["uri"], copy assets, then write_scene_spec(out_dir, spec_dict).
        raise NotImplementedError


class Importer(object):
    """Blender side. Reads a Bundle into the CURRENT scene. Geometry + spec only -
    pipeline applies materials/world/camera/look/preset afterward."""
    name = None  # == SceneSpec.geometry.transport

    def can_load(self, bundle_ref):
        # (str) -> bool
        raise NotImplementedError

    def load(self, bundle_ref):
        # (str) -> LoadedScene
        raise NotImplementedError


class LoadedScene(object):
    """Return of Importer.load: parsed spec + handles to what landed in Blender."""

    def __init__(self, spec_dict, root_collection=None, node_to_object=None):
        self.spec = spec_dict                       # dict (validate vs schema)
        self.root_collection = root_collection      # bpy Collection | None
        self.node_to_object = node_to_object or {}  # {Element.node: bpy object}


def check_contract_version(spec_dict):
    # (dict) -> None ; refuse on MAJOR mismatch, warn on MINOR
    got = str(spec_dict.get("contract_version", "0.0.0"))
    if got.split(".")[0] != CONTRACT_VERSION.split(".")[0]:
        raise ValueError("Incompatible contract major version: bundle=%s code=%s"
                         % (got, CONTRACT_VERSION))


# --- registry: select transport by name (== SceneSpec.geometry.transport) ---
_EXPORTERS = {}
_IMPORTERS = {}


def register_exporter(e):
    _EXPORTERS[e.name] = e


def register_importer(i):
    _IMPORTERS[i.name] = i


def get_exporter(name):
    return _EXPORTERS[name]


def get_importer(name):
    return _IMPORTERS[name]


def has_importer(name):
    return name in _IMPORTERS
