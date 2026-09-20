"""Element-material repair unit test (no Revit, no Blender - pure Python).

Locks the fix for the "phases and colours instead of materials" bug: extraction
is WYSIWYG, so Revit reports the material the VIEW displays - which is the phase
graphic override, not the element's own surface. bir_extract/element_materials.py
rewrites those back.

The Revit API is faked (a positive-int ElementId, GetMaterialIds, compound
structures, material parameters, a category material), which is enough to
exercise every branch of the resolver plus the group-merge arithmetic.

Run: python tests/test_element_materials.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_LIB = os.path.join(_ROOT, "lib")
for p in (_ROOT, _LIB):
    if p not in sys.path:
        sys.path.insert(0, p)

from bir_extract import element_materials as em  # noqa: E402


# --- fake Revit API ----------------------------------------------------------
class _EId(object):
    """ElementId: _compat.id_value() reads .Value (Revit 2024+)."""
    def __init__(self, value):
        self.Value = int(value)

    def __eq__(self, other):
        return isinstance(other, _EId) and other.Value == self.Value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("_EId", self.Value))


class _BuiltInParameter(object):
    STRUCTURAL_MATERIAL_PARAM = "STRUCTURAL_MATERIAL_PARAM"
    MATERIAL_ID_PARAM = "MATERIAL_ID_PARAM"


class _ElementIdClass(object):
    InvalidElementId = _EId(-1)


class _FakeDB(object):
    ElementId = _ElementIdClass
    BuiltInParameter = _BuiltInParameter


class _Param(object):
    def __init__(self, eid):
        self._eid = eid

    def AsElementId(self):
        return self._eid


class _Material(object):
    def __init__(self, mid):
        self.Id = _EId(mid)


class _Category(object):
    def __init__(self, name="Walls", material=None):
        self.Name = name
        self.Material = material


class _Layer(object):
    def __init__(self, mid):
        self.MaterialId = _EId(mid)


class _CompoundStructure(object):
    def __init__(self, mids):
        self._mids = mids

    def GetLayers(self):
        return [_Layer(m) for m in self._mids]


class _Type(object):
    def __init__(self, tid, geo=(), compound=None, param=None):
        self.Id = _EId(tid)
        self._geo = list(geo)
        self._compound = _CompoundStructure(compound) if compound else None
        self._param = param
        self.calls = 0

    def GetMaterialIds(self, painted):
        self.calls += 1
        return [] if painted else [_EId(m) for m in self._geo]

    def GetCompoundStructure(self):
        return self._compound

    def get_Parameter(self, bip):
        if self._param is not None and bip == \
                _BuiltInParameter.STRUCTURAL_MATERIAL_PARAM:
            return _Param(_EId(self._param))
        return None


class _Element(object):
    """Counts instance-level GetMaterialIds calls so the test can prove the
    fast path really does avoid them."""

    def __init__(self, typ=None, geo=(), painted=(), param=None,
                 category=None):
        self._type = typ
        self._geo = list(geo)
        self._painted = list(painted)
        self._param = param
        self.Category = category if category is not None else _Category()
        self.instance_calls = 0

    def GetTypeId(self):
        return self._type.Id if self._type is not None else _EId(-1)

    def GetMaterialIds(self, painted):
        self.instance_calls += 1
        src = self._painted if painted else self._geo
        return [_EId(m) for m in src]

    def GetCompoundStructure(self):
        return None

    def get_Parameter(self, bip):
        if self._param is not None and bip == \
                _BuiltInParameter.STRUCTURAL_MATERIAL_PARAM:
            return _Param(_EId(self._param))
        return None


class _Doc(object):
    def __init__(self, types=None):
        self._types = types or {}

    def GetElement(self, eid):
        return self._types.get(eid.Value)


def _doc_for(*types):
    return _Doc(dict((t.Id.Value, t) for t in types))


def _setup():
    em.DB = _FakeDB
    return em.Resolver(enabled=True)


# --- tests -------------------------------------------------------------------
def test_genuine_material_is_left_alone_without_instance_calls():
    """The no-overrides case: the view agrees with the type, so the resolver must
    change nothing AND must not pay for the instance-level reads."""
    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    assert res.repair(doc, el, "mat_", ["mat_7"]) is None
    assert el.instance_calls == 0, "fast path must not touch the instance"
    assert res.repaired == 0


def test_phase_override_is_repaired_to_the_single_own_material():
    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    # Revit reported material 999 - the phase graphic override, which the
    # element does not own.
    out = res.repair(doc, el, "mat_", ["mat_999"])
    assert out == {"mat_999": "mat_7"}, out
    assert res.repaired == 1
    assert res.approximate == 0, "single own material -> an EXACT repair"


def test_compound_structure_exterior_layer_wins_as_primary():
    """A wall overridden by phase: prefer the outermost (finish) layer over the
    structural core, because that is the face the render sees."""
    res = _setup()
    typ = _Type(100, geo=[9, 4], compound=[4, 9])   # exterior finish 4, core 9
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    out = res.repair(doc, el, "mat_", ["mat_999"])
    assert out == {"mat_999": "mat_4"}, out
    assert res.approximate == 1, "multi-material -> flagged as approximate"


def test_multi_material_report_is_never_touched():
    """The blast-radius guard: two reported materials prove the view preserved
    the element's real split, so nothing is repaired even though the element
    owns neither id."""
    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    assert res.repair(doc, el, "mat_", ["mat_501", "mat_502"]) is None
    assert res.repaired == 0
    assert res.skipped == 1


def test_default_only_is_not_a_repair():
    res = _setup()
    typ = _Type(100, geo=[7])
    doc = _doc_for(typ)
    assert res.repair(doc, _Element(typ=typ), "mat_", ["mat_default"]) is None


def test_painted_material_is_genuine():
    """Paint is instance-level, so it misses the type cache and must be rescued
    by the instance pass instead of being repaired away."""
    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ, painted=[42])
    doc = _doc_for(typ)
    assert res.repair(doc, el, "mat_", ["mat_42"]) is None
    assert el.instance_calls > 0, "a miss must fall through to the instance"
    assert res.repaired == 0


def test_parameter_and_category_materials_count_as_owned():
    res = _setup()
    typ = _Type(100, param=55)
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    assert res.repair(doc, el, "mat_", ["mat_55"]) is None

    res = _setup()
    typ2 = _Type(101)
    el2 = _Element(typ=typ2, category=_Category("Walls", _Material(66)))
    doc2 = _doc_for(typ2)
    assert res.repair(doc2, el2, "mat_", ["mat_66"]) is None


def test_no_own_material_keeps_the_view_material():
    """Curtain panels / in-place geometry: with nothing better to offer, keeping
    the view's material renders as SOMETHING, which beats flat grey."""
    res = _setup()
    el = _Element(typ=None)
    doc = _Doc()
    assert res.repair(doc, el, "mat_", ["mat_999"]) is None
    assert res.repaired == 0
    assert res.unresolved == 1


def test_linked_prefix_namespace_is_preserved():
    """Link materials are keyed mat_l<n>_<id>; a repair must stay in that
    namespace or materials.py resolves it against the wrong document."""
    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    out = res.repair(doc, el, "mat_l2_", ["mat_l2_999"])
    assert out == {"mat_l2_999": "mat_l2_7"}, out
    # a host-prefixed key is not in this element's namespace -> ignored
    assert res.repair(doc, el, "mat_l2_", ["mat_999"]) is None


def test_type_cache_is_namespaced_by_prefix():
    """Host material 7 and link material 7 are different materials; a cache
    keyed on the type id alone would confuse them."""
    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ)
    doc = _doc_for(typ)
    assert res.repair(doc, el, "mat_", ["mat_7"]) is None
    calls = typ.calls
    assert res.repair(doc, el, "mat_", ["mat_7"]) is None
    assert typ.calls == calls, "second element of the type must hit the cache"
    assert res.repair(doc, el, "mat_l1_", ["mat_l1_7"]) is None
    assert typ.calls > calls, "a different namespace must not reuse the entry"


def test_disabled_resolver_is_a_no_op():
    em.DB = _FakeDB
    res = em.Resolver(enabled=False)
    typ = _Type(100, geo=[7])
    assert res.repair(_doc_for(typ), _Element(typ=typ), "mat_",
                      ["mat_999"]) is None
    assert res.repaired == 0


def test_repair_never_raises_on_a_hostile_element():
    class _Hostile(object):
        Category = None

        def GetTypeId(self):
            raise Exception("boom")

        def GetMaterialIds(self, painted):
            raise Exception("boom")

        def get_Parameter(self, bip):
            raise Exception("boom")

    res = _setup()
    assert res.repair(_Doc(), _Hostile(), "mat_", ["mat_999"]) is None
    assert res.repair(None, None, "mat_", ["mat_999"]) is None


def test_kill_switch_env_var():
    for val, expected in (("0", False), ("false", False), ("no", False),
                          ("off", False), ("1", True), ("", True)):
        os.environ["BLENDIT_MATERIAL_REPAIR"] = val
        assert em.repair_enabled() is expected, val
    del os.environ["BLENDIT_MATERIAL_REPAIR"]
    assert em.repair_enabled() is True


# --- remap_groups ------------------------------------------------------------
def test_remap_groups_merges_with_the_index_offset():
    """Two groups collapsing onto one key must have the second group's triangle
    indices shifted by the first's vertex count - forgetting the offset shreds
    the mesh into garbage triangles."""
    groups = {
        "mat_1": {"verts": [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                  "tris": [(0, 1, 2)]},
        "mat_2": {"verts": [(2, 0, 0), (3, 0, 0), (2, 1, 0)],
                  "tris": [(0, 1, 2)]},
    }
    out = em.remap_groups(groups, {"mat_1": "mat_9", "mat_2": "mat_9"})
    assert list(out.keys()) == ["mat_9"], out.keys()
    merged = out["mat_9"]
    assert len(merged["verts"]) == 6
    assert merged["tris"] == [(0, 1, 2), (3, 4, 5)], merged["tris"]
    # every index still points at a real vertex
    for tri in merged["tris"]:
        for idx in tri:
            assert 0 <= idx < len(merged["verts"])


def test_remap_groups_partial_and_empty():
    groups = {"mat_1": {"verts": [(0, 0, 0)], "tris": []},
              "mat_2": {"verts": [(1, 0, 0)], "tris": []}}
    assert em.remap_groups(groups, None) is groups
    assert em.remap_groups(groups, {}) is groups
    out = em.remap_groups(groups, {"mat_1": "mat_7"})
    assert sorted(out.keys()) == ["mat_2", "mat_7"], out.keys()


def test_key_material_id():
    assert em.key_material_id("mat_123", "mat_") == 123
    assert em.key_material_id("mat_l3_123", "mat_l3_") == 123
    assert em.key_material_id("mat_default", "mat_") is None
    assert em.key_material_id("mat_l3_123", "mat_") is None   # wrong namespace
    assert em.key_material_id("", "mat_") is None
    assert em.key_material_id("mat_abc", "mat_") is None


# --- wiring ------------------------------------------------------------------
def test_geometry_extract_element_emits_the_repaired_material():
    """The 3-line wiring is where this fix can silently do nothing: prove the
    repaired key reaches BOTH the MeshData and the spec `elements` entry, since
    materials.py resolves names off the spec and the glTF binds off the mesh."""
    from bir_extract import geometry

    res = _setup()
    typ = _Type(100, geo=[7])
    el = _Element(typ=typ, category=_Category("Generic Models"))
    el.Id = _EId(4242)
    doc = _doc_for(typ)
    el.get_Geometry = lambda opt: object()      # non-None: content comes from _collect

    original_collect = geometry._collect
    geometry._collect = lambda geo, groups, prefix="mat_", xf=None: groups.update(
        {"mat_999": {"verts": [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                     "tris": [(0, 1, 2)]}})
    try:
        meshes, elements, mids = geometry.extract_element(
            doc, el, None, resolver=res)
    finally:
        geometry._collect = original_collect

    assert len(meshes) == 1 and len(elements) == 1, (meshes, elements)
    assert meshes[0].material_id == "mat_7", meshes[0].material_id
    assert elements[0]["material_id"] == "mat_7", elements[0]
    assert mids == set(["mat_7"]), mids
    assert "mat_999" not in mids, "the phase override must not reach the bundle"
    assert res.repaired == 1


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in _tests:
        fn()
    print("ELEMENT MATERIALS OK (%d tests)" % len(_tests))
