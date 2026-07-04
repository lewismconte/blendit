"""Poche - solid fill of the elements a section / plan cut passes through.

The section cut is a camera near-clip: it slices geometry but leaves the openings
hollow (you see the cut outline, not a filled cut face). Poche caps those openings
with real geometry so the cut reads solid, the way an architect pochés a plan or
section. We bisect each visible mesh at the cut plane, fill the resulting cut
contours (edgenet_fill handles wall rings + holes), and collect just the caps into
one `BIR_Poche` object with a flat fill material. It is excluded from Line Art (the
cut outline is already drawn) and nudged just past the near clip so it isn't clipped.

Everything is guarded per object: a mesh that won't bisect / fill is skipped, never
an exception that aborts the drawing.
"""
import bpy
import bmesh
import mathutils

POCHE_OBJ = "BIR_Poche"
POCHE_MAT = "BIR_PocheMat"
_GROUND = "BIR_Ground"
_NUDGE = 0.003          # metres past the near clip so the caps aren't clipped away


def clear_poche():
    """Remove the poche object + mesh (if present)."""
    obj = bpy.data.objects.get(POCHE_OBJ)
    if obj is None:
        return
    me = obj.data
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        return
    if me is not None and me.users == 0:
        try:
            bpy.data.meshes.remove(me)
        except Exception:
            pass


def _poche_material(color):
    mat = bpy.data.materials.get(POCHE_MAT)
    if mat is None:
        mat = bpy.data.materials.new(POCHE_MAT)
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        emit = nt.nodes.new("ShaderNodeEmission")      # flat tone, engine-independent
        nt.links.new(emit.outputs[0], out.inputs["Surface"])
    for n in mat.node_tree.nodes:
        if n.type == "EMISSION":
            n.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    return mat


def _append_faces(out, bm):
    """Append bm's geometry into the `out` bmesh (no bpy.ops.join)."""
    vmap = {}
    for v in bm.verts:
        vmap[v] = out.verts.new(v.co)
    for f in bm.faces:
        try:
            out.faces.new([vmap[v] for v in f.verts])
        except ValueError:
            pass            # duplicate face - ignore


def _caps_for(obj, deps, plane_co, plane_no):
    """A bmesh holding ONLY the cut-face caps for one object (world space), or None."""
    try:
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
    except Exception:
        return None
    if me is None or len(me.polygons) == 0:
        try:
            ev.to_mesh_clear()
        except Exception:
            pass
        return None
    bm = bmesh.new()
    caps = None
    try:
        bm.from_mesh(me)
        bm.transform(obj.matrix_world)                 # -> world space
        # Weld coincident verts: Revit/glTF meshes have per-face (unshared) verts,
        # so without this the cut edges don't connect into a fillable loop.
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6,
                                     plane_co=plane_co, plane_no=plane_no)
        cut_edges = [g for g in res.get("geom_cut", [])
                     if isinstance(g, bmesh.types.BMEdge)]
        if cut_edges:
            # contextual_create caps the cut loop with an n-gon (the "F" fill).
            fill = bmesh.ops.contextual_create(bm, geom=cut_edges)
            cap_faces = set(fill.get("faces", []))
            if cap_faces:
                drop = [f for f in bm.faces if f not in cap_faces]
                if drop:
                    bmesh.ops.delete(bm, geom=drop, context="FACES")
                if bm.faces:
                    caps = bm            # hand ownership to the caller
    except Exception:
        caps = None
    finally:
        try:
            ev.to_mesh_clear()
        except Exception:
            pass
    if caps is None:
        bm.free()
    return caps


def build_poche(plane_co, plane_no, color=(0.13, 0.13, 0.13), exclude=None):
    """(Re)build the BIR_Poche object: cut-face caps at the plane, flat-filled.
    plane_co / plane_no are world-space (mathutils.Vector). Returns the object or
    None if nothing was cut."""
    clear_poche()
    exclude = set(exclude or ())
    exclude.update((_GROUND, POCHE_OBJ))
    try:
        plane_no = mathutils.Vector(plane_no).normalized()
        plane_co = mathutils.Vector(plane_co)
    except Exception:
        return None
    deps = bpy.context.evaluated_depsgraph_get()
    out = bmesh.new()
    made = False
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH" or obj.name in exclude:
            continue
        caps = _caps_for(obj, deps, plane_co, plane_no)
        if caps is None:
            continue
        _append_faces(out, caps)
        caps.free()
        made = True
    if not made or len(out.faces) == 0:
        out.free()
        return None
    me = bpy.data.meshes.new(POCHE_OBJ)
    out.to_mesh(me)
    out.free()
    obj = bpy.data.objects.new(POCHE_OBJ, me)
    bpy.context.scene.collection.objects.link(obj)
    me.materials.append(_poche_material(color))
    obj.location = plane_no * _NUDGE                   # just past the near clip
    try:
        obj.lineart.usage = "EXCLUDE"                  # cut outline is already drawn
    except Exception:
        pass
    return obj
