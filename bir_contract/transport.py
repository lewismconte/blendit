"""Blendit - transport layer (the seam).

Exporter : Revit side, IronPython 2.7 -> writes a Bundle
Importer : Blender side, CPython 3     -> reads a Bundle into Blender

KEEP THIS MODULE IRONPYTHON-2.7 SAFE: no f-strings, no type annotations in
signatures, no dataclasses. Type hints are in comments. The on-disk Bundle
(entry point scene_spec.json) is the cross-process contract.
"""
import datetime
import json
import os

CONTRACT_VERSION = "0.3.0"
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


def write_json(path, obj):
    # (str, obj) -> None ; the ONE safe JSON writer for both sides.
    # ensure_ascii=False + UTF-8 bytes: a Revit string with a non-ASCII char (a
    # material name carrying the (R) sign, an accented view name / path) crashes
    # IronPython's ascii json encoder - it decodes the high byte through the system
    # code page and throws. Emitting UTF-8 sidesteps that entirely; read_json reads
    # it back as UTF-8. Old all-ASCII files are byte-identical either way.
    data = json.dumps(obj, indent=2, ensure_ascii=False)
    if hasattr(data, "encode"):
        data = data.encode("utf-8")
    f = open(path, "wb")
    try:
        f.write(data)
    finally:
        f.close()


def read_json(path):
    # (str) -> obj ; reads what write_json wrote (UTF-8). The default text open()
    # would misread non-ASCII on Windows (cp1252). Same on IronPython 2.7 / CPython.
    f = open(path, "rb")
    try:
        raw = f.read()
    finally:
        f.close()
    if hasattr(raw, "decode"):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def write_scene_spec(bundle_dir, spec_dict):
    # (str, dict) -> str   ; returns bundle_ref (path to scene_spec.json)
    if not os.path.isdir(bundle_dir):
        os.makedirs(bundle_dir)
    path = bundle_spec_path(bundle_dir)
    write_json(path, spec_dict)
    return path


def read_scene_spec(bundle_ref):
    # (str) -> dict
    if bundle_ref.endswith(".json") and os.path.isfile(bundle_ref):
        path = bundle_ref
    else:
        path = bundle_spec_path(bundle_ref)
    return read_json(path)


def bundle_dir_of(bundle_ref):
    # (str) -> str
    return os.path.dirname(bundle_ref) if bundle_ref.endswith(".json") else bundle_ref


# --- output naming (shared so Revit + Blender exports match) ------------------
# EVERY export - the Revit headless render, and the Blender captures / finals /
# vector drawings - uses this one  <prefix>_<YYYY-MM-DD_HHMMSS>.<ext>  scheme, so
# the files read identically and sort chronologically on both sides.
def timestamp():
    # () -> str   ; filename-safe local timestamp, second resolution
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def stamped_name(prefix, ext):
    # (str, str) -> str
    # e.g. stamped_name("render", "png") -> "render_2026-06-29_103045.png"
    return "%s_%s.%s" % (prefix, timestamp(), str(ext).lstrip("."))


def fit_resolution(res, aspect):
    # (list[int, int], float) -> list[int, int]
    # Keep the long edge; set the short edge from `aspect` (width/height). Shared so
    # the Revit-side extraction and the Blender-side override refit stay identical -
    # a view framed to its crop must keep the crop's aspect or the framing silently
    # changes. IronPython-2.7 + CPython safe (plain int/round/max).
    try:
        long_edge = max(int(res[0]), int(res[1]))
    except Exception:
        long_edge = 1600
    if aspect >= 1.0:
        return [long_edge, max(1, int(round(long_edge / aspect)))]
    return [max(1, int(round(long_edge * aspect))), long_edge]


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
    got_parts = got.split(".")
    code_parts = CONTRACT_VERSION.split(".")
    if got_parts[0] != code_parts[0]:
        raise ValueError("Incompatible contract major version: bundle=%s code=%s"
                         % (got, CONTRACT_VERSION))
    got_minor = got_parts[1] if len(got_parts) > 1 else "0"
    if got_minor != code_parts[1]:
        print("Blendit: contract minor version differs (bundle=%s, code=%s) - "
              "newer optional fields may be missing or ignored."
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
