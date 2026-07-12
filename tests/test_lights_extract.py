"""Light extraction unit test (no Revit, no Blender - pure Python).

Locks the position bug fix: a fixture's world position must come from its
Location.Point (its real placement in the building), NOT the light node's
family-local transform (which put every downlight at ~(0,0,mount_height), so
1035 fixtures clumped onto the vertical axis). Linked fixtures get the link
transform applied - the same rule OnRPC uses for trees.

Run: python tests/test_lights_extract.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_LIB = os.path.join(_ROOT, "lib")
for p in (_ROOT, _LIB):
    if p not in sys.path:
        sys.path.insert(0, p)

from bir_extract import lights  # noqa: E402


class _XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class _Loc(object):
    def __init__(self, p):
        self.Point = p


class _Fixture(object):
    """A FamilyInstance-ish fixture: has a Location.Point and FacingOrientation,
    and no readable photometric params (forces the default lamp)."""
    def __init__(self, x, y, z, facing=None):
        self.Location = _Loc(_XYZ(x, y, z))
        self.FacingOrientation = facing or _XYZ(0.0, 0.0, 1.0)  # faces up

    def GetTypeId(self):
        raise Exception("no type")          # skip the type-param lookup

    def get_Parameter(self, bip):
        return None


class _LinkXf(object):
    """Simulates a linked model placed +100 X / +200 Y from the host."""
    def OfPoint(self, p):
        return _XYZ(p.X + 100.0, p.Y + 200.0, p.Z)

    def OfVector(self, v):
        return v


class _Doc(object):
    def __init__(self, fixtures):
        self._fx = fixtures

    def GetElement(self, eid):
        return self._fx.get(eid)


def test_positions_from_location_not_clumped():
    doc = _Doc({1: _Fixture(5, 6, 9), 2: _Fixture(15, -3, 9)})
    refs = [
        {"doc": doc, "scope": 0, "eid": 1, "link_xf": None},
        {"doc": doc, "scope": 5, "eid": 2, "link_xf": _LinkXf()},
    ]
    res = lights.resolve_lights(refs, doc)
    assert len(res) == 2, res
    # host: straight from Location.Point (spread across the plan, not (0,0,z))
    assert res[0]["position"] == [5.0, 6.0, 9.0], res[0]["position"]
    # linked: Location lifted through the link transform only
    assert res[1]["position"] == [115.0, 197.0, 9.0], res[1]["position"]
    # the two fixtures are at DIFFERENT x/y - the clumping regression guard
    assert res[0]["position"][0] != res[1]["position"][0]
    assert res[0]["position"][1] != res[1]["position"][1]


def test_up_facing_flips_down():
    doc = _Doc({1: _Fixture(0, 0, 9, facing=_XYZ(0, 0, 1))})
    res = lights.resolve_lights([{"doc": doc, "scope": 0, "eid": 1,
                                  "link_xf": None}], doc)
    assert res[0]["direction"][2] < 0.0, "ceiling fixture must shine DOWN"


def test_empty_and_missing_are_graceful():
    assert lights.resolve_lights([], None) == []
    assert lights.resolve_lights(None, None) == []
    doc = _Doc({})
    assert lights.resolve_lights([{"doc": doc, "eid": 99, "link_xf": None}],
                                 doc) == []


if __name__ == "__main__":
    test_positions_from_location_not_clumped()
    test_up_facing_flips_down()
    test_empty_and_missing_are_graceful()
    print("LIGHTS EXTRACT OK")
