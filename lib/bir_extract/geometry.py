"""Tessellate the elements visible in a 3D view into MeshData.

Output is Revit-native: feet, Z-up. Faces are grouped by material within each
element, so a multi-material element yields one MeshData per material (each with a
stable `node` key that the SceneSpec `elements` list maps back to Revit metadata).
No normals are emitted -> Blender's glTF import computes flat face normals, which
is what you want for crisp hard-surface architecture.
"""
from bir_contract.transport import MeshData
from bir_extract import _compat

DB = _compat.DB
_DEFAULT_MAT = "mat_default"


def extract_geometry(doc, view3d, progress=None):
    """-> (meshes, elements, material_ids). `progress(done, total)` is called
    periodically so the Revit side can show a progress bar."""
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

    for idx, elem in enumerate(elems):
        if progress is not None and (idx % 25 == 0 or idx == total - 1):
            try:
                progress(idx + 1, total)
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

    return meshes, elements, material_ids


def _collect(geo, groups):
    for obj in geo:
        if isinstance(obj, DB.Solid):
            if obj.Faces.Size > 0:
                _collect_solid(obj, groups)
        elif isinstance(obj, DB.GeometryInstance):
            try:
                inst_geo = obj.GetInstanceGeometry()  # already in model coords
            except Exception:
                inst_geo = None
            if inst_geo is not None:
                _collect(inst_geo, groups)


def _collect_solid(solid, groups):
    for face in solid.Faces:
        try:
            mat_key = _face_material_key(face)
        except Exception:
            mat_key = _DEFAULT_MAT
        try:
            mesh = face.Triangulate()
        except Exception:
            mesh = None
        if mesh is None:
            continue
        g = groups.setdefault(mat_key, {"verts": [], "tris": []})
        base = len(g["verts"])
        for vi in range(mesh.Vertices.Count):
            p = mesh.Vertices[vi]
            g["verts"].append((p.X, p.Y, p.Z))
        for ti in range(mesh.NumTriangles):
            tri = mesh.get_Triangle(ti)
            g["tris"].append((base + int(tri.get_Index(0)),
                              base + int(tri.get_Index(1)),
                              base + int(tri.get_Index(2))))


def _face_material_key(face):
    mid = face.MaterialElementId
    if mid is None or mid == DB.ElementId.InvalidElementId:
        return _DEFAULT_MAT
    return "mat_%s" % _compat.id_value(mid)


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
