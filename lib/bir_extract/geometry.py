"""Tessellate the elements visible in a 3D view into MeshData.

Output is Revit-native: feet, Z-up. Faces are grouped by material within each
element, so a multi-material element yields one MeshData per material (each with a
stable `node` key that the SceneSpec `elements` list maps back to Revit metadata).
No normals are emitted -> Blender's glTF import computes flat face normals, which
is what you want for crisp hard-surface architecture.

Collected geometry: Solids (tessellated per face), GeometryInstances (recursed),
and bare DB.Mesh objects (imported CAD / DirectShape content, which never comes
through as a Solid and would otherwise silently vanish from the render).
"""
from bir_contract.transport import MeshData
from bir_extract import _compat

DB = _compat.DB
_DEFAULT_MAT = "mat_default"


def extract_geometry(doc, view3d, progress=None):
    """-> (meshes, elements, material_ids, link_docs). `progress(done, total)`
    is called periodically so the Revit side can show a progress bar.

    `link_docs` maps a material-key PREFIX -> the LINKED Document that owns the
    material element ids under it. Geometry from a RevitLinkInstance carries
    material ids belonging to the LINK's document, not the host's - resolving
    them against the host either loses the material (grey default) or, worse,
    silently picks whatever host material happens to share the integer id. So
    link materials are keyed "mat_l<instance-id>_<mat-id>" and materials.py
    resolves them against the right document."""
    opt = DB.Options()
    # Prefer the view's own representation (respects detail level + visibility);
    # fall back to a Fine model representation if setting the view is rejected.
    try:
        opt.View = view3d
    except Exception:
        opt.DetailLevel = DB.ViewDetailLevel.Fine
    opt.ComputeReferences = False
    opt.IncludeNonVisibleObjects = False

    collector = (DB.FilteredElementCollector(doc, view3d.Id)
                 .WhereElementIsNotElementType())
    elems = list(collector)
    total = len(elems)

    meshes = []
    elements = []
    material_ids = set()
    link_docs = {}

    for idx, elem in enumerate(elems):
        if progress is not None and (idx % 25 == 0 or idx == total - 1):
            try:
                progress(idx + 1, total)
            except Exception:
                pass
        try:
            if isinstance(elem, DB.RevitLinkInstance):
                # Link instances expose NO geometry via get_Geometry (verified
                # live on Revit 2025: empty with a view Options, None without) -
                # walk the linked document's own elements instead. BEFORE the
                # geometry fetch: a link's own geo is empty/None by design.
                _extract_link(view3d, elem, meshes, elements, material_ids,
                              link_docs, progress)
                continue
        except Exception:
            pass

        try:
            geo = elem.get_Geometry(opt)
        except Exception:
            geo = None
        if geo is None:
            continue

        groups = {}
        try:
            _collect(geo, groups)
        except Exception:
            groups = {}
        if not groups:
            continue

        cat = _category_name(elem)
        eid = str(_compat.id_value(elem.Id))
        level = _level_name(doc, elem)
        single = len(groups) == 1
        n = 0
        for mat_key, data in groups.items():
            if not data["tris"]:
                continue
            node = "%s_%s" % (cat, eid) if single else "%s_%s_%d" % (cat, eid, n)
            n += 1
            meshes.append(MeshData(node, data["verts"], data["tris"],
                                   material_id=mat_key))
            elements.append({"node": node, "element_id": eid, "category": cat,
                             "level": level, "material_id": mat_key})
            material_ids.add(mat_key)

    return meshes, elements, material_ids, link_docs


def _extract_link(view3d, link, meshes, elements, material_ids, link_docs,
                  progress=None):
    """Extract a RevitLinkInstance by walking the LINKED document's elements,
    each transformed by the instance's total transform into host coordinates.
    Material keys are namespaced per instance ("mat_l<id>_<matid>") so
    materials.py resolves them against the link's own document. Fidelity note:
    the link's content renders at Fine detail regardless of the host view's
    per-link visibility overrides (only a fully hidden link is skipped)."""
    ldoc = None
    try:
        ldoc = link.GetLinkDocument()
    except Exception:
        pass
    if ldoc is None:                     # unloaded link
        return
    try:
        if link.IsHidden(view3d):
            return
    except Exception:
        pass
    lid = _compat.id_value(link.Id)
    prefix = "mat_l%s_" % lid
    link_docs[prefix] = ldoc

    try:
        xf = link.GetTotalTransform()
        if xf.IsIdentity:
            xf = None
    except Exception:
        xf = None

    opt = DB.Options()
    opt.DetailLevel = DB.ViewDetailLevel.Fine   # host views can't filter ldoc
    opt.ComputeReferences = False
    opt.IncludeNonVisibleObjects = False

    try:
        lelems = list(DB.FilteredElementCollector(ldoc)
                      .WhereElementIsNotElementType()
                      .WhereElementIsViewIndependent())
    except Exception:
        return
    ltotal = len(lelems)
    for lidx, le in enumerate(lelems):
        if progress is not None and lidx % 100 == 0:
            try:
                progress(lidx + 1, ltotal)
            except Exception:
                pass
        try:
            geo = le.get_Geometry(opt)
        except Exception:
            geo = None
        if geo is None:
            continue
        groups = {}
        try:
            _collect(geo, groups, prefix, xf)
        except Exception:
            groups = {}
        if not groups:
            continue
        cat = _category_name(le)
        eid = "l%s_%s" % (lid, _compat.id_value(le.Id))
        level = _level_name(ldoc, le)
        single = len(groups) == 1
        n = 0
        for mat_key, data in groups.items():
            if not data["tris"]:
                continue
            node = "%s_%s" % (cat, eid) if single else "%s_%s_%d" % (cat, eid, n)
            n += 1
            meshes.append(MeshData(node, data["verts"], data["tris"],
                                   material_id=mat_key))
            elements.append({"node": node, "element_id": eid, "category": cat,
                             "level": level, "material_id": mat_key})
            material_ids.add(mat_key)


def _collect(geo, groups, prefix="mat_", xf=None):
    for obj in geo:
        if isinstance(obj, DB.Solid):
            if obj.Faces.Size > 0:
                _collect_solid(obj, groups, prefix, xf)
        elif isinstance(obj, DB.Mesh):
            # Imported CAD / DirectShape geometry arrives as a bare Mesh.
            _append_mesh(obj, _mesh_material_key(obj, prefix), groups, xf)
        elif isinstance(obj, DB.GeometryInstance):
            try:
                inst_geo = obj.GetInstanceGeometry()  # already in model coords
            except Exception:
                inst_geo = None
            if inst_geo is not None:
                _collect(inst_geo, groups, prefix, xf)


def _collect_solid(solid, groups, prefix="mat_", xf=None):
    for face in solid.Faces:
        try:
            mat_key = _face_material_key(face, prefix)
        except Exception:
            mat_key = _DEFAULT_MAT
        try:
            mesh = face.Triangulate()
        except Exception:
            mesh = None
        if mesh is None:
            continue
        _append_mesh(mesh, mat_key, groups, xf)


def _append_mesh(mesh, mat_key, groups, xf=None):
    """Append a Revit DB.Mesh's triangles into the per-material group. `xf`
    (a link instance's total transform) maps link coords -> host coords."""
    g = groups.setdefault(mat_key, {"verts": [], "tris": []})
    base = len(g["verts"])
    if xf is None:
        for vi in range(mesh.Vertices.Count):
            p = mesh.Vertices[vi]
            g["verts"].append((p.X, p.Y, p.Z))
    else:
        for vi in range(mesh.Vertices.Count):
            p = xf.OfPoint(mesh.Vertices[vi])
            g["verts"].append((p.X, p.Y, p.Z))
    for ti in range(mesh.NumTriangles):
        tri = mesh.get_Triangle(ti)
        g["tris"].append((base + int(tri.get_Index(0)),
                          base + int(tri.get_Index(1)),
                          base + int(tri.get_Index(2))))


def _mesh_material_key(mesh, prefix="mat_"):
    try:
        mid = mesh.MaterialElementId
        if mid is None or mid == DB.ElementId.InvalidElementId:
            return _DEFAULT_MAT
        return "%s%s" % (prefix, _compat.id_value(mid))
    except Exception:
        return _DEFAULT_MAT


def _face_material_key(face, prefix="mat_"):
    mid = face.MaterialElementId
    if mid is None or mid == DB.ElementId.InvalidElementId:
        return _DEFAULT_MAT
    return "%s%s" % (prefix, _compat.id_value(mid))


def _category_name(elem):
    try:
        if elem.Category is not None:
            return elem.Category.Name.replace(" ", "")
    except Exception:
        pass
    return "Element"


def _level_name(doc, elem):
    try:
        lid = elem.LevelId
        if lid is not None and lid != DB.ElementId.InvalidElementId:
            lvl = doc.GetElement(lid)
            if lvl is not None:
                return lvl.Name
    except Exception:
        pass
    return ""
