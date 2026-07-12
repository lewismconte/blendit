"""WYSIWYG extraction: Revit's CustomExporter walks a 3D view's DISPLAYED
geometry - host and linked models, with every visibility rule applied (hidden
elements/categories, per-link overrides, phases, design options, section box,
crop) - so the bundle contains exactly what the user sees in the view. This is
the same mechanism real exporters use; geometry.py's collector walk remains the
fallback (and the 2D-view path), where link content can only be approximated.

Material ids inside links are namespaced per linked DOCUMENT ("mat_l<n>_<id>")
and resolved against that document by materials.extract_materials.

IronPython 2.7 + pure ASCII. Keep it that way.
"""
from bir_contract.transport import MeshData
from bir_extract import _compat

DB = _compat.DB
_DEFAULT_MAT = "mat_default"


def available():
    return DB is not None and hasattr(DB, "CustomExporter")


def _node_eid(raw, scope):
    """Element identifier used in the node name. Host elements (scope 0) keep the
    bare id; linked elements are namespaced per PLACEMENT (scope), so the SAME
    linked document placed twice produces distinct node names instead of colliding
    (one copy would otherwise lose its material at the merge step)."""
    return str(raw) if scope == 0 else "l%d_%s" % (scope, raw)


def extract_view(doc, view3d, progress=None):
    """-> (meshes, elements, material_ids, link_docs, lights) for exactly what the
    view displays. Raises on failure - the caller falls back to the collector walk.
    `lights` is the raw OnLight capture (refs + placement); build_scene_spec
    resolves photometrics via lights.resolve_lights."""
    ctx = _Context(doc, view3d, progress)
    exporter = DB.CustomExporter(doc, ctx)
    for attr, val in (("IncludeGeometricObjects", False),
                      ("ShouldStopOnError", False)):
        try:
            setattr(exporter, attr, val)
        except Exception:
            pass
    exporter.Export(view3d)
    if not ctx.meshes:
        raise RuntimeError("CustomExporter produced no geometry")
    _append_rpc_proxies(doc, view3d, ctx)
    return ctx.meshes, ctx.elements, ctx.material_ids, ctx.link_docs, ctx.lights


def _append_rpc_proxies(doc, view3d, ctx):
    """Tessellate the proxy meshes of RPC elements (trees / entourage) the
    exporter reported but gave no geometry for. Host elements use the view's
    own representation; link elements use Fine detail + the link transform."""
    from bir_extract import geometry as geo
    for cur_doc, prefix, xf, eid, scope in ctx.rpc_elements:
        try:
            el = cur_doc.GetElement(eid)
            if el is None:
                continue
            opt = DB.Options()
            if cur_doc is doc:
                try:
                    opt.View = view3d
                except Exception:
                    opt.DetailLevel = DB.ViewDetailLevel.Fine
            else:
                opt.DetailLevel = DB.ViewDetailLevel.Fine
            opt.ComputeReferences = False
            opt.IncludeNonVisibleObjects = False
            g = el.get_Geometry(opt)
            if g is None:
                continue
            groups = {}
            geo._collect(g, groups, prefix, xf)
            if not groups:
                continue
            cat = "Element"
            try:
                if el.Category is not None:
                    cat = el.Category.Name.replace(" ", "")
            except Exception:
                pass
            raw = _compat.id_value(eid)
            key = _node_eid(raw, scope)         # prefix still namespaces MATERIALS
            single = len(groups) == 1
            n = 0
            for mat_key, data in groups.items():
                if not data["tris"]:
                    continue
                node = ("%s_%s" % (cat, key) if single
                        else "%s_%s_%d" % (cat, key, n))
                n += 1
                ctx.meshes.append(MeshData(node, data["verts"], data["tris"],
                                           material_id=mat_key))
                ctx.elements.append({"node": node, "element_id": key,
                                     "category": cat, "level": "",
                                     "material_id": mat_key})
                ctx.material_ids.add(mat_key)
        except Exception:
            pass


class _Context(DB.IExportContext):
    """Accumulates polymeshes per (element, material) with the full transform
    stack applied, tracking the document stack so link elements keep their own
    identity and material namespace."""

    def __init__(self, doc, view3d, progress=None):
        self._host = doc
        self._progress = progress
        self._docs = [doc]                    # document stack (links push)
        self._prefixes = ["mat_"]             # material-key prefix per linked DOC
        self._xf = [None]                     # transform stack (None = identity)
        self._elem_ids = []                   # element-id stack (links nest)
        self._scope = [0]                     # per-PLACEMENT id (0 = host); a fresh
        self._link_seq = 0                    # id per OnLinkBegin so two placements
        #                                       of ONE linked doc don't collide
        self._groups = {}                     # (elem key) -> {mat_key: verts/tris}
        self._mat_key = _DEFAULT_MAT
        self._link_count = 0
        self._done = 0
        # Progress ESTIMATE: host count + each visible link's element count - one
        # monotonic bar. Counted with GetElementCount() + a class-filtered pass over
        # just the link INSTANCES, so it doesn't materialize (and discard) the whole
        # host element list before the export walk even starts.
        self._total = 0
        try:
            self._total = (DB.FilteredElementCollector(doc, view3d.Id)
                           .WhereElementIsNotElementType().GetElementCount())
            links = (DB.FilteredElementCollector(doc, view3d.Id)
                     .OfClass(DB.RevitLinkInstance))
            for e in links:
                try:
                    if not e.IsHidden(view3d):
                        ldoc = e.GetLinkDocument()
                        if ldoc is not None:
                            self._total += (
                                DB.FilteredElementCollector(ldoc)
                                .WhereElementIsNotElementType()
                                .GetElementCount())
                except Exception:
                    pass
        except Exception:
            pass
        self.meshes = []
        self.elements = []
        self.material_ids = set()
        self.link_docs = {}
        self.rpc_elements = []                # (doc, prefix, link_xf, elem_id, scope)
        self._rpc_seen = set()
        self.lights = []                      # [{doc, scope, eid, pos, dir}] (OnLight)
        self._light_seen = set()
        self._link_xf = [None]                # LINK-scope transform only (no
        self._view = view3d                   # instance transforms - see OnRPC)

    # --- lifecycle ------------------------------------------------------------
    def Start(self):
        return True

    def Finish(self):
        pass

    def IsCanceled(self):
        return False

    def OnViewBegin(self, node):
        # 0..15; middling detail == the viewport's own tessellation quality.
        try:
            node.LevelOfDetail = 8
        except Exception:
            pass
        return DB.RenderNodeAction.Proceed

    def OnViewEnd(self, element_id):
        pass

    # --- scopes ----------------------------------------------------------------
    def OnElementBegin(self, element_id):
        self._elem_ids.append(element_id)
        self._done += 1
        if self._progress is not None and self._done % 50 == 0:
            try:
                total = max(self._total, self._done)
                self._progress(min(self._done, total), total)
            except Exception:
                pass
        return DB.RenderNodeAction.Proceed

    def OnElementEnd(self, element_id):
        try:
            self._flush_element(element_id)
        except Exception:
            pass
        if self._elem_ids:
            self._elem_ids.pop()

    def OnInstanceBegin(self, node):
        self._push_xf(node)
        return DB.RenderNodeAction.Proceed

    def OnInstanceEnd(self, node):
        if len(self._xf) > 1:                 # guard: never underflow on an
            self._xf.pop()                    # unmatched End (would IndexError the
        #                                       next [-1] and abort the whole walk)

    def OnLinkBegin(self, node):
        self._push_xf(node)
        ldoc = None
        try:
            ldoc = node.GetDocument()
        except Exception:
            pass
        if ldoc is not None:
            prefix = None
            for known, d in self.link_docs.items():
                if d is ldoc:
                    prefix = known
                    break
            if prefix is None:
                self._link_count += 1
                prefix = "mat_l%d_" % self._link_count
                self.link_docs[prefix] = ldoc
            self._docs.append(ldoc)
            self._prefixes.append(prefix)
        else:
            self._docs.append(self._docs[-1])
            self._prefixes.append(self._prefixes[-1])
        self._link_xf.append(self._xf[-1])    # the composed transform AT link entry
        self._link_seq += 1                   # unique per placement (even repeats of
        self._scope.append(self._link_seq)    # the same linked doc)
        return DB.RenderNodeAction.Proceed

    def OnLinkEnd(self, node):
        # Guarded pops: an unmatched End must never underflow a stack (the next
        # [-1] read would IndexError and abort the whole extraction).
        if len(self._xf) > 1:
            self._xf.pop()
        if len(self._docs) > 1:
            self._docs.pop()
            self._prefixes.pop()
        if len(self._link_xf) > 1:
            self._link_xf.pop()
        if len(self._scope) > 1:
            self._scope.pop()

    def OnFaceBegin(self, node):
        return DB.RenderNodeAction.Proceed

    def OnFaceEnd(self, node):
        pass

    def OnLight(self, node):
        # WYSIWYG light capture: the exporter only calls this for lights actually
        # DISPLAYED in the view (visibility already applied). Record the fixture
        # element + its LINK transform only, exactly like OnRPC - NOT the light
        # node's own transform. That node transform is the light's LOCAL offset
        # inside the family (a downlight sits at ~(0,0,mount_height) in family
        # space), so using it clumped every fixture onto the vertical axis.
        # lights.resolve_lights derives the real world position from the
        # element's Location.Point (already in its document's model coords), with
        # the link transform applied for linked fixtures - the RPC insight.
        # Never raise - a bad light must not abort the geometry walk.
        try:
            eid = self._elem_ids[-1] if self._elem_ids else None
            if eid is None:
                return
            scope = self._scope[-1]
            key = (scope, _compat.id_value(eid))
            if key in self._light_seen:
                return
            self._light_seen.add(key)
            self.lights.append({"doc": self._docs[-1], "scope": scope,
                                "eid": eid, "link_xf": self._link_xf[-1]})
        except Exception:
            pass

    def OnRPC(self, node):
        # RPC content (planting / entourage - the trees) yields NO polymesh
        # from the exporter. Remember the element + its scope; extract_view
        # tessellates the RPC proxy mesh afterwards so trees don't vanish.
        # Record the LINK transform only - element.get_Geometry returns MODEL
        # coordinates (instance placement already applied), so carrying the
        # walk's instance transform here double-transforms and the trees end
        # up scattered in the sky.
        try:
            if self._elem_ids:
                # Key on the per-placement scope, not doc-stack DEPTH: two different
                # links at the same depth can hold RPC elements whose (per-document)
                # ids coincide - a depth key would drop the second tree.
                key = (self._scope[-1],
                       _compat.id_value(self._elem_ids[-1]))
                if key not in self._rpc_seen:
                    self._rpc_seen.add(key)
                    self.rpc_elements.append(
                        (self._docs[-1], self._prefixes[-1], self._link_xf[-1],
                         self._elem_ids[-1], self._scope[-1]))
        except Exception:
            pass

    # --- content ---------------------------------------------------------------
    def OnMaterial(self, node):
        try:
            mid = node.MaterialId
            if mid is None or mid == DB.ElementId.InvalidElementId:
                self._mat_key = _DEFAULT_MAT
            else:
                self._mat_key = "%s%s" % (self._prefixes[-1],
                                          _compat.id_value(mid))
        except Exception:
            self._mat_key = _DEFAULT_MAT

    def OnPolymesh(self, mesh):
        try:
            key = self._elem_key()
            groups = self._groups.setdefault(key, {})
            g = groups.setdefault(self._mat_key, {"verts": [], "tris": []})
            base = len(g["verts"])
            xf = self._xf[-1]
            pts = mesh.GetPoints()
            if xf is None:
                for p in pts:
                    g["verts"].append((p.X, p.Y, p.Z))
            else:
                for p in pts:
                    q = xf.OfPoint(p)
                    g["verts"].append((q.X, q.Y, q.Z))
            for f in mesh.GetFacets():
                g["tris"].append((base + f.V1, base + f.V2, base + f.V3))
        except Exception:
            pass

    # --- helpers ---------------------------------------------------------------
    def _push_xf(self, node):
        try:
            t = node.GetTransform()
            if t is None or t.IsIdentity:
                self._xf.append(self._xf[-1])
                return
            top = self._xf[-1]
            self._xf.append(t if top is None else top.Multiply(t))
        except Exception:
            self._xf.append(self._xf[-1])

    def _elem_key(self):
        eid = self._elem_ids[-1] if self._elem_ids else None
        # (per-placement scope, element id) - unique across host + every link
        # placement, so two placements of ONE linked doc never merge or collide.
        return (self._scope[-1],
                _compat.id_value(eid) if eid is not None else 0)

    def _flush_element(self, element_id):
        key = self._elem_key()
        groups = self._groups.pop(key, None)
        if not groups:
            return
        cur_doc = self._docs[-1]
        raw = _compat.id_value(element_id)
        eid = _node_eid(raw, self._scope[-1])   # material key stays doc-scoped
        cat = "Element"
        level = ""
        try:
            el = cur_doc.GetElement(element_id)
            if el is not None and el.Category is not None:
                cat = el.Category.Name.replace(" ", "")
        except Exception:
            pass
        single = len(groups) == 1
        n = 0
        for mat_key, data in groups.items():
            if not data["tris"]:
                continue
            node = "%s_%s" % (cat, eid) if single else "%s_%s_%d" % (cat, eid, n)
            n += 1
            self.meshes.append(MeshData(node, data["verts"], data["tris"],
                                        material_id=mat_key))
            self.elements.append({"node": node, "element_id": eid,
                                  "category": cat, "level": level,
                                  "material_id": mat_key})
            self.material_ids.add(mat_key)


