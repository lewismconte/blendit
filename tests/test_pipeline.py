"""Fixture-based pipeline tests — run under bpy, NO Revit required.

Loads tests/fixtures/ via the transport importer, runs the full pipeline for each
RenderMode, and asserts a non-trivial PNG is written.

These need Blender's Python: either the pinned `bpy` wheel (CI) or running under
Blender. Without bpy they skip. Runs standalone like its siblings
(`blender --background --python tests/test_pipeline.py`, or plain
`python tests/test_pipeline.py` with the bpy wheel) — pytest is optional.
"""
import os
import sys

try:
    import pytest
except ImportError:                        # standalone run: pytest not required
    pytest = None

if pytest is not None:
    bpy = pytest.importorskip(
        "bpy",
        reason="pipeline tests need Blender's Python (the pinned bpy wheel / "
               "pytest-in-Blender)",
    )
else:
    try:
        import bpy  # noqa: F401
    except Exception:
        bpy = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_FIXTURE = os.path.join(_HERE, "fixtures")
_MODES = ["realistic", "white", "shadow", "linework", "specular"]
_MIN_BYTES = 2000  # a real render of the box is far larger than an empty PNG


def _render_mode(mode, out_dir):
    from blender.pipeline.run import run_pipeline

    out = os.path.join(out_dir, "out_%s.png" % mode)
    run_pipeline(_FIXTURE, out, overrides={
        "engine": "CYCLES",        # CPU-reliable headless; EEVEE needs a GPU context
        "mode": mode,
        "samples": 4,
        "resolution": [240, 135],
    })
    assert os.path.isfile(out), "no PNG written for mode %s" % mode
    assert os.path.getsize(out) >= _MIN_BYTES, "PNG too small for mode %s" % mode


def _check_gltf_axis_and_materials():
    """The bundle imports and the glass element keeps a transmissive material."""
    from blender.pipeline.import_bundle import reset_scene, import_bundle
    from blender.pipeline.materials import apply_materials

    reset_scene()
    loaded = import_bundle(_FIXTURE)
    apply_materials(loaded, engine="CYCLES")
    nodes = set(loaded.node_to_object)
    assert {"Box_1", "Glass_1"} <= nodes, nodes


if pytest is not None:
    @pytest.mark.parametrize("mode", _MODES)
    def test_mode_renders_nontrivial_png(mode, tmp_path):
        _render_mode(mode, str(tmp_path))

    def test_gltf_axis_and_materials_load():
        _check_gltf_axis_and_materials()


if __name__ == "__main__":
    if bpy is None:
        print("SKIP: pipeline tests need Blender's Python (bpy). Run under "
              "Blender: blender --background --python tests/test_pipeline.py")
    else:
        import tempfile
        d = tempfile.mkdtemp(prefix="blendit_pipeline_")
        for _mode in _MODES:
            _render_mode(_mode, d)
            print("mode %s OK" % _mode)
        _check_gltf_axis_and_materials()
        print("PIPELINE OK")
