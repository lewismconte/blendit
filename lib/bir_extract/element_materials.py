"""Repair VIEW-SUBSTITUTED material ids back to the element's OWN material.

THE BUG THIS FIXES: extraction is deliberately WYSIWYG - view_export.py walks
the view with CustomExporter, geometry.py sets Options.View - so Revit reports
whatever material the VIEW DISPLAYS. When a view carries phase graphic overrides
(Manage > Phases > Graphic Overrides has a Material column, populated in most
office templates), Revit substitutes the phase's override material for the
element's real one. materials.py then faithfully reports that material's name,
so the bundle arrives in Blender full of materials called "Phase - New" /
"Existing" instead of "Brick - Buff" - flat, wrong, and invisible to the
name-keyword surface library in blender/pipeline/material_library.py.

THE FIX (mechanism-agnostic on purpose): ask the ELEMENT what materials it owns.
If the view-reported material is one of them, it is genuine - keep it. If it is
not, the view substituted something, so rewrite it to the element's own material.
This catches phase overrides without naming them, and it is a no-op on models
that have no overrides (the reported material always matches), so the risk of a
regression is confined to elements Revit already disagreed with itself about.

WHAT IT CANNOT FIX: materials that are genuinely assigned but badly NAMED -
imported CAD and DirectShape content whose materials Revit auto-creates as
"Render Material 128-128-128". Those really are the element's own material;
there is nothing better to resolve to. Fixing how those render is a Blender-side
concern (material_library name matching).

PRECISION: a repair is EXACT when the element owns exactly one material.
When it owns several, the override collapsed every face onto one reported
material and the per-face split is unrecoverable, so we pick a primary (see
`own_materials` for the order - the exterior compound-structure layer first,
because that is the face a renderer mostly sees) and count it as approximate.
`Resolver.summary()` reports both counts so the loss is never silent.

BLAST RADIUS: an element for which the view reported two or more materials is
never touched - see the guard in `Resolver._repair`. Substitution is
per-element and all-or-nothing, so a preserved multi-material split proves
there was no substitution, and that one check is what stops the heuristic from
mangling a model whose materials come from somewhere GetMaterialIds
under-reports.

Kill switch: set BLENDIT_MATERIAL_REPAIR=0 to fall back to the raw view
materials.

IronPython 2.7 + pure ASCII. Keep it that way.
"""
import os

from bir_extract import _compat

DB = _compat.DB
_DEFAULT_MAT = "mat_default"

# Instance-then-type parameters that hold a material as an ElementId. Resolved
# by NAME via getattr, so a Revit version lacking one is harmless.
_MATERIAL_BIPS = ("STRUCTURAL_MATERIAL_PARAM", "MATERIAL_ID_PARAM")


def repair_enabled():
    """False when BLENDIT_MATERIAL_REPAIR is set to 0/false/no (the kill switch
    for a heuristic that only a live Revit can really exercise)."""
    try:
        val = os.environ.get("BLENDIT_MATERIAL_REPAIR", "")
    except Exception:
        return True
    return str(val).strip().lower() not in ("0", "false", "no", "off")


# --- key helpers -------------------------------------------------------------
def key_material_id(key, prefix):
    """Material KEY ("mat_123" / "mat_l2_123") -> its integer material id, or
    None for mat_default / a key that is not in this element's namespace."""
    if not key or key == _DEFAULT_MAT:
        return None
    if not key.startswith(prefix):
        return None
    try:
        return int(key[len(prefix):])
    except Exception:
        return None


def remap_groups(groups, mapping):
    """Rewrite the material keys of ONE element's {mat_key: {verts, tris}} dict.

    Groups that collapse onto the same key are concatenated with the triangle
    indices offset by the running vertex count - forgetting that offset would
    silently shred the merged mesh into garbage triangles. Keys are visited in
    sorted order so the result is deterministic (IronPython dicts are not).
    """
    if not mapping:
        return groups
    out = {}
    for key in sorted(groups.keys()):
        data = groups[key]
        new_key = mapping.get(key, key)
        target = out.get(new_key)
        if target is None:
            out[new_key] = data
            continue
        base = len(target["verts"])
        target["verts"].extend(data["verts"])
        for tri in data["tris"]:
            target["tris"].append((base + tri[0], base + tri[1], base + tri[2]))
    return out


# --- element -> its own materials --------------------------------------------
def own_materials(doc, el):
    """-> ordered list of integer material ids the ELEMENT itself owns.

    Ordered PRIMARY FIRST; the order is the whole heuristic for multi-material
    elements, so it is explicit:

      1. compound-structure layers, exterior -> interior (walls / floors /
         roofs / ceilings). The outermost layer is the finish a renderer
         actually sees, which beats the thickest structural core.
      2. the instance's own geometry materials.
      3. the type's geometry materials.
      4. painted materials (deliberate per-face user intent, but we cannot tell
         WHICH face from here, so it must not outrank the real surfaces).
      5. structural-material parameters, instance then type.
      6. the category material ("by category" assignment).

    Within 2-4 Revit does not define an order, so a multi-material family
    instance gets an arbitrary-but-stable pick. Deduplicated, ids only.
    """
    typ = _element_type(doc, el)
    compound, type_rest = _type_materials(typ, el)
    inst = _instance_materials(el)
    return _dedup(compound + inst + type_rest)


def _element_type(doc, el):
    try:
        tid = el.GetTypeId()
    except Exception:
        return None
    if _valid_id(tid) is None:
        return None
    try:
        return doc.GetElement(tid)
    except Exception:
        return None


def _type_materials(typ, el):
    """-> (compound-structure layer ids, other TYPE-level ids). Split out because
    only these are cacheable per element type - see Resolver._type_part."""
    compound = _compound_layer_ids(typ) if typ is not None else []
    rest = []
    if typ is not None:
        rest.extend(_collection_ids(_material_ids(typ, False)))
        rest.extend(_param_material_ids(typ))
    cat = _category_material_id(el)
    if cat is not None:
        rest.append(cat)
    return _dedup(compound), _dedup(rest)


def _instance_materials(el):
    """-> INSTANCE-level ids (never cacheable: painted faces and instance
    material parameters differ between two instances of one type)."""
    out = []
    out.extend(_collection_ids(_material_ids(el, False)))
    out.extend(_collection_ids(_material_ids(el, True)))     # painted
    out.extend(_param_material_ids(el))
    return _dedup(out)


def _material_ids(el, painted):
    try:
        return el.GetMaterialIds(painted)
    except Exception:
        return None


def _compound_layer_ids(typ):
    """Wall/floor/roof/ceiling layer materials, exterior -> interior (the order
    GetLayers() returns them in)."""
    try:
        cs = typ.GetCompoundStructure()
    except Exception:
        return []
    if cs is None:
        return []
    out = []
    try:
        for layer in cs.GetLayers():
            val = _valid_id(layer.MaterialId)
            if val is not None:
                out.append(val)
    except Exception:
        pass
    return out


def _param_material_ids(el):
    out = []
    if DB is None:
        return out
    for name in _MATERIAL_BIPS:
        bip = getattr(DB.BuiltInParameter, name, None)
        if bip is None:
            continue
        try:
            param = el.get_Parameter(bip)
            if param is None:
                continue
            val = _valid_id(param.AsElementId())
            if val is not None:
                out.append(val)
        except Exception:
            pass
    return out


def _category_material_id(el):
    try:
        cat = el.Category
        if cat is None:
            return None
        mat = cat.Material
        if mat is None:
            return None
        return _valid_id(mat.Id)
    except Exception:
        return None


def _collection_ids(coll):
    out = []
    if coll is None:
        return out
    try:
        for eid in coll:
            val = _valid_id(eid)
            if val is not None:
                out.append(val)
    except Exception:
        pass
    return out


def _valid_id(eid):
    """ElementId -> a positive integer material id, else None. Material elements
    always have positive ids; the negatives are built-in categories/parameters,
    so this also screens out InvalidElementId on a Revit that compares oddly."""
    if eid is None:
        return None
    try:
        if DB is not None and eid == DB.ElementId.InvalidElementId:
            return None
    except Exception:
        pass
    try:
        val = int(_compat.id_value(eid))
    except Exception:
        return None
    return val if val > 0 else None


def _dedup(vals):
    out = []
    for val in vals:
        if val not in out:
            out.append(val)
    return out


# --- the resolver ------------------------------------------------------------
class Resolver(object):
    """Per-extraction material repair, with a per-element-type cache.

    Built for the cost profile of a real model: the check that runs for EVERY
    element is one GetTypeId() plus a dict lookup against that type's cached
    material set, so a model with no view overrides costs a single Revit call
    per element - noise next to tessellation. Only a MISS (the view reported
    something the type does not own) drops to the instance-level reads.
    """

    def __init__(self, enabled=None):
        self.enabled = repair_enabled() if enabled is None else bool(enabled)
        self._type_part_cache = {}     # (prefix, type id) -> (compound, rest)
        self.repaired = 0              # material keys rewritten
        self.approximate = 0           # ...of which lost a per-face split
        self.unresolved = 0            # substituted, but no own material found
        self.skipped = 0               # multi-material elements, left untouched

    def repair(self, doc, el, prefix, mat_keys):
        """-> {old_key: new_key} for the keys of ONE element that the view
        substituted, or None when there is nothing to change. Pass the result to
        remap_groups. Never raises: a repair failure must leave the raw view
        material in place, not abort the extraction."""
        if not self.enabled or el is None or doc is None:
            return None
        try:
            return self._repair(doc, el, prefix, mat_keys)
        except Exception:
            return None

    def _repair(self, doc, el, prefix, mat_keys):
        reported = []
        for key in mat_keys or ():
            val = key_material_id(key, prefix)
            if val is not None:
                reported.append((key, val))
        if not reported:
            return None                    # only mat_default - nothing to repair
        if len(reported) > 1:
            # THE BLAST-RADIUS GUARD, and it is cheaper than any Revit call.
            # A view substitution is per-ELEMENT and all-or-nothing: a phase
            # graphic override paints every face of the element with its ONE
            # material. So the moment the view reports two or more materials for
            # an element, it preserved that element's real multi-material split
            # and there is nothing to repair. Skipping these also means the
            # repair can never mangle geometry whose materials arrive from
            # somewhere GetMaterialIds under-reports (nested family
            # subcategories being the usual suspect) - the only way this
            # heuristic could make a correct model worse.
            self.skipped += 1
            return None

        compound, type_rest = self._type_part(doc, el, prefix)
        known = set(compound) | set(type_rest)
        unknown = [pair for pair in reported if pair[1] not in known]
        if not unknown:
            return None                    # FAST PATH: the view agrees with the type

        inst = _instance_materials(el)
        unknown = [pair for pair in unknown if pair[1] not in set(inst)]
        if not unknown:
            return None                    # genuine: painted / instance material

        own = _dedup(list(compound) + list(inst) + list(type_rest))
        if not own:
            # Nothing better to offer (curtain panels, in-place geometry whose
            # material lives on nested subcategories, ...). Keeping the view's
            # material is the lesser evil: it at least renders as something.
            self.unresolved += len(unknown)
            return None

        primary = own[0]
        lossy = len(own) > 1
        out = {}
        for key, _val in unknown:
            out[key] = "%s%s" % (prefix, primary)
            self.repaired += 1
            if lossy:
                self.approximate += 1
        return out

    def _type_part(self, doc, el, prefix):
        """Cached (compound, rest) for the element's TYPE.

        The type ELEMENT is only fetched on a cache miss - resolving the id is
        cheap, materializing the type and reading its compound structure is not,
        and on a normal model this is hit once per type and then never again.
        The cache key includes the material prefix, because a linked document's
        material ids live in its own namespace and would otherwise collide with
        the host's.
        """
        cache_key = None
        try:
            tid = el.GetTypeId()
            if _valid_id(tid) is not None:
                cache_key = (prefix, _compat.id_value(tid))
        except Exception:
            cache_key = None
        if cache_key is not None:
            cached = self._type_part_cache.get(cache_key)
            if cached is not None:
                return cached
        typ = _element_type(doc, el)
        part = _type_materials(typ, el)
        if cache_key is not None:
            self._type_part_cache[cache_key] = part
        return part

    def summary(self):
        """One log line, or None when nothing was repaired."""
        if not self.repaired and not self.unresolved:
            return None
        return ("Blendit: repaired %d view-substituted material(s) back to the "
                "element's own material (%d approximated on multi-material "
                "elements, %d left as-is - no own material found). Phase "
                "graphic overrides are the usual cause. Set "
                "BLENDIT_MATERIAL_REPAIR=0 to disable."
                % (self.repaired, self.approximate, self.unresolved))

    def log_summary(self):
        try:
            line = self.summary()
            if line:
                print(line)
        except Exception:
            pass
