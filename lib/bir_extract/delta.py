"""Dirty element ids -> a live-sync patch (docs/live-sync-plan.md, Phase A).

Runs on Application.Idling (a valid API read context). Each dirty element
re-extracts through the SAME extract_element the full Load View uses, so a
patched node is byte-identical to a full re-extract of it. The delta unit is
the ELEMENT: its whole node-set is replaced, and the old-vs-new node diff
covers the material-edit case where the node COUNT changes (a mesh that
splits into two materials, or collapses back to one).

The node index ({element_id_str: [node, ...]}) is what makes removals
possible: a DELETED element no longer exists, so its category (and therefore
its node names) can only come from bookkeeping. It is seeded from the loaded
bundle's scene_spec.json (load_node_index) and updated by every build_patch
call; the sync engine keeps it in a pyRevit envvar between flushes.

Scope (v1): HOST elements only. A dirty RevitLinkInstance (a moved/reloaded
link) is skipped with a note - re-extracting a whole linked model is a Load
View, not a patch. View visibility is re-checked per flush: a "modified"
element that got hidden/filtered emits a removal, not stale geometry.

IronPython 2.7 / pure ASCII (the Revit import chain).
"""
from bir_contract import transport
from bir_extract import _compat
from bir_extract import geometry

DB = _compat.DB


def load_node_index(bundle_ref):
    """Seed {element_id: [node, ...]} from the loaded bundle's spec. Link
    elements (element_id "l<instance>_<id>") are indexed too - harmless, and a
    future link-aware delta can use them."""
    index = {}
    try:
        spec = transport.read_scene_spec(bundle_ref)
    except Exception:
        return index
    for e in spec.get("geometry", {}).get("elements", []):
        eid = str(e.get("element_id") or "")
        node = e.get("node")
        if not eid or not node:
            continue
        index.setdefault(eid, []).append(node)
    return index


def _visible_ids(doc, view3d):
    """Ids of the elements the view can currently see (the WYSIWYG check)."""
    ids = set()
    try:
        collector = (DB.FilteredElementCollector(doc, view3d.Id)
                     .WhereElementIsNotElementType())
        for e in collector:
            try:
                ids.add(_compat.id_value(e.Id))
            except Exception:
                pass
    except Exception:
        pass
    return ids


def build_patch(doc, view3d, dirty_ids, deleted_ids, node_index):
    """-> (meshes, removed_nodes). Mutates node_index to match the patch.

    dirty_ids   : iterable of int element ids (added + modified)
    deleted_ids : iterable of int element ids (gone from the document)
    node_index  : {element_id_str: [node, ...]} - the live bookkeeping
    """
    meshes = []
    removed = []

    for eid in deleted_ids or []:
        key = str(eid)
        removed.extend(node_index.pop(key, []))

    dirty = [e for e in (dirty_ids or [])]
    if not dirty:
        return meshes, removed

    opt = geometry.view_options(view3d)
    visible = _visible_ids(doc, view3d)

    for eid in dirty:
        key = str(eid)
        old_nodes = node_index.get(key, [])
        elem = None
        try:
            elem = doc.GetElement(_compat.make_element_id(eid))
        except Exception:
            elem = None
        if elem is None or eid not in visible:
            # Gone, or no longer visible in THIS view (hidden / filtered /
            # phased out): that is a removal, not stale geometry.
            removed.extend(old_nodes)
            node_index.pop(key, None)
            continue
        try:
            if isinstance(elem, DB.RevitLinkInstance):
                # A whole linked model changed placement/content: that is a
                # Load View, not a patch. Leave its nodes as they are.
                print("Blendit sync: link instance %s changed - re-run "
                      "Load View to refresh linked content" % key)
                continue
        except Exception:
            pass

        m, e, mids = geometry.extract_element(doc, elem, opt)
        new_nodes = [md.node for md in m]
        if not new_nodes:
            # An element the view sees but that yields no geometry (annotation,
            # empty family): whatever it used to show is gone.
            removed.extend(old_nodes)
            node_index.pop(key, None)
            continue
        for node in old_nodes:
            if node not in new_nodes:
                removed.append(node)   # material split/merge changed the set
        meshes.extend(m)
        node_index[key] = new_nodes

    return meshes, removed
