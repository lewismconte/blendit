"""Contract single-source-of-truth checks (PLAIN CPYTHON -- no Revit, no bpy).

Locks two things so they can't silently drift:
  * the JSON schema's render.mode enum == the canonical RENDER_MODES tuple, and
  * CONTRACT_VERSION has exactly one owner (transport.py), re-exported by scene_spec.

Run standalone:   python tests/test_contract.py
Or under pytest:  pytest tests/test_contract.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bir_contract import scene_spec, transport


def _schema_modes():
    path = os.path.join(_ROOT, "bir_contract", "scene_spec.schema.json")
    with open(path) as f:
        schema = json.load(f)
    return schema["$defs"]["render"]["properties"]["mode"]["enum"]


def test_schema_modes_match_render_modes():
    schema_modes = _schema_modes()
    assert set(schema_modes) == set(scene_spec.RENDER_MODES), (
        "schema render.mode enum %s != RENDER_MODES %s"
        % (sorted(schema_modes), sorted(scene_spec.RENDER_MODES)))
    # no dupes in either list
    assert len(schema_modes) == len(set(schema_modes)), "duplicate mode in schema enum"
    assert len(scene_spec.RENDER_MODES) == len(set(scene_spec.RENDER_MODES)), \
        "duplicate mode in RENDER_MODES"


def test_contract_version_single_source():
    # scene_spec re-exports transport's CONTRACT_VERSION (one owner, no duplicate
    # literal). They must be the same value.
    assert scene_spec.CONTRACT_VERSION == transport.CONTRACT_VERSION


if __name__ == "__main__":
    test_schema_modes_match_render_modes()
    test_contract_version_single_source()
    print("modes:", sorted(scene_spec.RENDER_MODES))
    print("contract_version:", scene_spec.CONTRACT_VERSION,
          "(==", transport.CONTRACT_VERSION + ")")
    print("CONTRACT OK")
