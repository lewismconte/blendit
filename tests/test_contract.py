"""Contract single-source-of-truth checks (PLAIN CPYTHON -- no Revit, no bpy).

Locks four things so they can't silently drift:
  * the JSON schema's render.mode enum == the canonical RENDER_MODES tuple,
  * CONTRACT_VERSION has exactly one owner (transport.py), re-exported by scene_spec,
  * the Revit-side mode catalog (bir_config.MODES + labels) covers every mode, and
  * the ribbon's Mode pulldown has a button per mode.

Run standalone:   python tests/test_contract.py
Or under pytest:  pytest tests/test_contract.py
"""
import importlib.util
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_LIB = os.path.join(_ROOT, "lib")
for _p in (_ROOT, _LIB):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bir_contract import scene_spec, transport
import bir_config


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


def test_revit_config_modes_match_render_modes():
    # The Revit ribbon / Settings offer bir_config.MODES; a mode missing there is
    # a shipped feature users can't reach (how "hatch" went missing once).
    assert set(bir_config.MODES) == set(scene_spec.RENDER_MODES), (
        "bir_config.MODES %s != RENDER_MODES %s"
        % (sorted(bir_config.MODES), sorted(scene_spec.RENDER_MODES)))
    assert set(bir_config.MODE_LABELS) == set(bir_config.MODES), (
        "MODE_LABELS keys %s != MODES %s"
        % (sorted(bir_config.MODE_LABELS), sorted(bir_config.MODES)))


def _load_registry():
    # registry.py is self-contained (no imports), so load it in isolation - going
    # through blender.pipeline.presets would run that package __init__, which imports
    # bpy. This keeps the check plain-CPython.
    path = os.path.join(_ROOT, "blender", "pipeline", "presets", "registry.py")
    spec = importlib.util.spec_from_file_location("_bir_registry_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_line_modes_are_render_modes():
    # LINE_MODES is the single source both the headless renderer and the interactive
    # session import; it must be a subset of the canonical modes, with no dupes.
    reg = _load_registry()
    line = set(reg.LINE_MODES)
    assert line <= set(scene_spec.RENDER_MODES), (
        "LINE_MODES %s not all in RENDER_MODES %s"
        % (sorted(line), sorted(scene_spec.RENDER_MODES)))
    assert len(reg.LINE_MODES) == len(line), "duplicate mode in LINE_MODES"


def test_live_mode_items_cover_render_modes():
    # The interactive N-panel mode dropdown (_MODE_ITEMS) is hand-labelled, so a new
    # mode can be added to the contract but forgotten here (silently absent from the
    # session UI). Text-scan its ids - no bpy needed.
    path = os.path.join(_ROOT, "blender", "interactive", "live.py")
    with open(path) as f:
        src = f.read()
    m = re.search(r"_MODE_ITEMS\s*=\s*\[(.*?)\]", src, re.S)
    assert m, "could not find _MODE_ITEMS in live.py"
    ids = set(re.findall(r'\(\s*"([a-z]+)"\s*,', m.group(1)))
    assert ids == set(scene_spec.RENDER_MODES), (
        "live.py _MODE_ITEMS %s != RENDER_MODES %s"
        % (sorted(ids), sorted(scene_spec.RENDER_MODES)))


def test_revit_side_is_pure_ascii():
    # The Revit side runs under IronPython 2.7, which rejects a source file with a
    # non-ASCII byte and no encoding declaration (PEP 263) - a hard SyntaxError at
    # import, invisible to a CPython py_compile (Py3 defaults to UTF-8 source). Guard
    # every Revit-side .py so a stray '(R)'/accent in a comment can't break the load.
    roots = ("lib", "bir_contract", "Blendit.tab")
    offenders = []
    for r in roots:
        base = os.path.join(_ROOT, r)
        for dirpath, _dirs, files in os.walk(base):
            if "__pycache__" in dirpath:
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, "rb") as f:
                    raw = f.read()
                bad = [i for i, b in enumerate(bytearray(raw)) if b > 127]
                if bad:
                    offenders.append("%s (first at byte %d)"
                                     % (os.path.relpath(path, _ROOT), bad[0]))
    assert not offenders, ("non-ASCII in Revit-side (IronPython) files:\n  "
                           + "\n  ".join(offenders))


def test_ribbon_has_a_button_per_mode():
    # Every render mode gets a pushbutton in the Mode pulldown (each script calls
    # bir_ui.set_mode("<key>")), so the ribbon can't silently miss a mode.
    pulldown = os.path.join(_ROOT, "Blendit.tab", "Render.panel", "Mode.pulldown")
    keys = set()
    for name in os.listdir(pulldown):
        script = os.path.join(pulldown, name, "script.py")
        if not os.path.isfile(script):
            continue
        with open(script) as f:
            m = re.search(r'set_mode\("([a-z]+)"\)', f.read())
        if m:
            keys.add(m.group(1))
    assert keys == set(scene_spec.RENDER_MODES), (
        "Mode pulldown buttons %s != RENDER_MODES %s"
        % (sorted(keys), sorted(scene_spec.RENDER_MODES)))


if __name__ == "__main__":
    test_schema_modes_match_render_modes()
    test_contract_version_single_source()
    test_revit_config_modes_match_render_modes()
    test_line_modes_are_render_modes()
    test_live_mode_items_cover_render_modes()
    test_revit_side_is_pure_ascii()
    test_ribbon_has_a_button_per_mode()
    print("modes:", sorted(scene_spec.RENDER_MODES))
    print("contract_version:", scene_spec.CONTRACT_VERSION,
          "(==", transport.CONTRACT_VERSION + ")")
    print("CONTRACT OK")
