# Test fixtures

A hand-written **bundle** that exercises the pipeline with **no Revit involved**:

- `scene_spec.json` — conforms to the schema.
- a `scene.glb` geometry payload (binary glTF, the same format the Revit exporter
  writes) — a couple of boxes and a glass pane, covering the **opaque** and
  **transparent** material paths.

Regenerate with `python tests/fixtures/build_fixture.py`; `tests/test_pipeline.py`
loads it and renders each mode.
