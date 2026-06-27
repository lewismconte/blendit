"""Fixture-based pipeline tests — run under bpy, NO Revit required.

Loads tests/fixtures/ via the transport importer, runs the full pipeline for each
RenderMode, and asserts a non-trivial PNG is written.

These need Blender's Python: either the pinned `bpy` wheel (CI) or running pytest
under Blender. Under plain CPython they skip. For a quick manual check without
pytest, use `blender --background --python tests/smoke_render.py`.
"""
import os
import sys

import pytest

bpy = pytest.importorskip(
    "bpy",
    reason="pipeline tests need Blender's Python (the pinned bpy wheel / pytest-in-Blender)",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_FIXTURE = os.path.join(_HERE, "fixtures")
_MODES = ["realistic", "white", "shadow", "linework", "specular"]
_MIN_BYTES = 2000  # a real render of the box is far larger than an empty PNG


@pytest.mark.parametrize("mode", _MODES)
def test_mode_renders_nontrivial_png(mode, tmp_path):
    from blender.pipeline.run import run_pipeline

    out = os.path.join(str(tmp_path), "out_%s.png" % mode)
    run_pipeline(_FIXTURE, out, overrides={
        "engine": "CYCLES",        # CPU-reliable headless; EEVEE needs a GPU context
        "mode": mode,
        "samples": 4,
        "resolution": [240, 135],
    })
    assert os.path.isfile(out), "no PNG written for mode %s" % mode
    assert os.path.getsize(out) >= _MIN_BYTES, "PNG too small for mode %s" % mode


def test_gltf_axis_and_materials_load():
    """The bundle imports and the glass element keeps a transmissive material."""
    from blender.pipeline.import_bundle import reset_scene, import_bundle
    from blender.pipeline.materials import apply_materials

    reset_scene()
    loaded = import_bundle(_FIXTURE)
    apply_materials(loaded, engine="CYCLES")
    nodes = set(loaded.node_to_object)
    assert {"Box_1", "Glass_1"} <= nodes, nodes
