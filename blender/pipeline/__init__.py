"""Engine-agnostic render pipeline (Blender side, CPython 3).

Ordered build steps applied after a transport loads geometry + the SceneSpec
(see run.py for the orchestration):
    import_bundle -> merge -> look -> camera -> world -> ground -> preset -> engine.

Materials (materials.py + material_library.py) and NPR (npr.py) are applied by the
per-mode presets in presets/; cache.py handles the prepared-.blend reuse for the
live session.
"""
