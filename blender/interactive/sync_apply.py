"""Live-sync applier: consume the patch spool, apply deltas by node id.

The Blender half of the delta link (docs/live-sync-plan.md). A `bpy.app.timers`
poll reads `<bundle>/patches/patch_<seq>.json` in seq order and applies each to
the running scene: updated nodes get a fresh mesh swapped in place, new nodes
become new objects, removed nodes are deleted. The session must be UN-MERGED
(per-element objects) - merge collapses the node identity deltas join on.

Everything here is pure data API - `mesh.from_pydata`, `obj.data` swap,
`bpy.data.objects.remove`. NEVER `bpy.ops`: operators silently fail in the
session's timer context (the white-mode merge bug; see merge.py).

Geometry in a patch is Revit-native feet, Z-up (raw MeshData - no glTF Y-up
intermediate). Replacing a mesh keeps the object's existing scale transform, so
it stays correctly scaled; ADDED objects get `scale_to_meters` set explicitly,
mirroring what import_bundle._apply_scale does for import roots.

Materials: an updated node keeps its object's current material slots (whatever
the active preset assigned - mode-agnostic). An added node copies the materials
of a sibling object that shares its material_id in the session spec; failing
that it falls back to a material stamped with the id (build_material stamps
"bir_material_id"), then to none (renders default grey; a full Load View is
always the recovery path).
"""
import os

import bpy

from bir_contract import transport

# Session wiring (set once by live.py when --watch is on).
_STATE = {
    "spool": None,        # str | None - the patch dir being polled
    "spec": None,         # dict | None - the session SceneSpec
    "collection": None,   # bpy Collection | None - where added objects link
    "applied": 0,         # patches applied this session
    "last_seq": 0,        # highest seq applied
    "status": "",         # one-line HUD status
}

POLL_INTERVAL = 0.5       # seconds between spool checks (timer return value)


def configure(spec=None, spool=None, collection=None):
    """Wire the applier to a session. Call before registering poll()."""
    if spec is not None:
        _STATE["spec"] = spec
    if spool is not None:
        _STATE["spool"] = spool
    if collection is not None:
        _STATE["collection"] = collection


def status():
    return _STATE["status"]


# --- node -> object ----------------------------------------------------------
def _find(node):
    """Object for a node id: exact name first (import names == spec nodes),
    then the stamped "node" id property (survives a Blender rename)."""
    obj = bpy.data.objects.get(node)
    if obj is not None:
        return obj
    for o in bpy.data.objects:
        try:
            if o.get("node") == node:
                return o
        except Exception:
            pass
    return None


def _scale_to_meters():
    spec = _STATE.get("spec") or {}
    try:
        return float(spec.get("units", {}).get("scale_to_meters", 1.0))
    except Exception:
        return 1.0


def _link_target():
    coll = _STATE.get("collection")
    if coll is not None:
        try:
            _ = coll.name          # dead reference check
            return coll
        except Exception:
            pass
    return bpy.context.scene.collection


# --- materials ----------------------------------------------------------------
def _material_for(node, material_id):
    """Best material for an ADDED node: a sibling object sharing material_id in
    the spec (inherits the active preset's look), else a material stamped with
    the id by build_material, else None."""
    if not material_id:
        return None
    spec = _STATE.get("spec") or {}
    for e in spec.get("geometry", {}).get("elements", []):
        if e.get("material_id") != material_id or e.get("node") == node:
            continue
        sib = _find(e.get("node"))
        if sib is not None and getattr(sib, "type", None) == "MESH":
            mats = [m for m in sib.data.materials if m is not None]
            if mats:
                return mats[0]
    for m in bpy.data.materials:
        try:
            if m.get("bir_material_id") == material_id:
                return m
        except Exception:
            pass
    return None


# --- the three delta operations ------------------------------------------------
def _build_mesh(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.validate()   # bad indices must not reach the render (crash territory)
    me.update()
    return me


def _apply_update(entry):
    node = entry.get("node")
    obj = _find(node)
    if obj is None:
        return _apply_add(entry)
    me = _build_mesh(node, entry.get("vertices") or [], entry.get("faces") or [])
    # Carry the object's CURRENT materials onto the fresh mesh - whatever the
    # active preset assigned (revit material, clay, crosshatch...) survives.
    old = obj.data
    try:
        for m in old.materials:
            me.materials.append(m)
    except Exception:
        pass
    obj.data = me
    try:
        if old is not None and old.users == 0:
            bpy.data.meshes.remove(old)
    except Exception:
        pass
    return "updated"


def _apply_add(entry):
    node = entry.get("node")
    me = _build_mesh(node, entry.get("vertices") or [], entry.get("faces") or [])
    mat = _material_for(node, entry.get("material_id"))
    if mat is not None:
        me.materials.append(mat)
    obj = bpy.data.objects.new(node, me)
    s = _scale_to_meters()
    obj.scale = (s, s, s)
    obj["node"] = node
    _link_target().objects.link(obj)
    return "added"


def _apply_remove(node):
    obj = _find(node)
    if obj is None:
        return "missing"
    data = obj.data
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        return "failed"
    try:
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)
    except Exception:
        pass
    return "removed"


def apply_patch(env):
    """Apply one patch envelope to the scene. -> counts dict (testable core)."""
    counts = {"updated": 0, "added": 0, "removed": 0, "missing": 0, "failed": 0}
    for entry in env.get("updated") or []:
        if not entry.get("node"):
            continue
        counts[_apply_update(entry)] += 1
    for node in env.get("removed") or []:
        counts[_apply_remove(node)] += 1
    # env["camera"] is Phase B (camera sync) - carried, not applied yet.
    _STATE["last_seq"] = max(_STATE["last_seq"], int(env.get("seq") or 0))
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return counts


def consume_spool():
    """Apply every pending patch in seq order, deleting each afterward.
    -> number applied. A patch that fails to apply is logged and dropped
    (a wedged spool is worse than a skipped patch; Load View is the recovery)."""
    spool = _STATE.get("spool")
    if not spool:
        return 0
    n = 0
    for path in transport.list_patches(spool):
        try:
            env = transport.read_patch(path)
            counts = apply_patch(env)
            n += 1
            _STATE["applied"] += 1
            _STATE["status"] = "Sync #%d: +%d ~%d -%d" % (
                env.get("seq") or 0, counts["added"], counts["updated"],
                counts["removed"])
        except Exception as exc:
            print("Blendit sync: patch %s failed (%s) - dropped"
                  % (os.path.basename(path), exc))
        try:
            os.remove(path)
        except Exception:
            pass
    return n


def poll():
    """The bpy.app.timers callback. Returns the next poll delay (never None -
    the watcher lives for the whole session)."""
    try:
        consume_spool()
    except Exception as exc:
        print("Blendit sync: poll error: %s" % exc)
    return POLL_INTERVAL
