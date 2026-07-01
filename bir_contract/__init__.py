"""Blendit shared contract package (the seam between Revit and Blender).

`transport.py` is IronPython-2.7 safe and importable on BOTH sides.
`scene_spec.py` is CPython-3 only (Blender + tests) - do not import under IronPython.
`scene_spec.schema.json` is the authoritative cross-language contract.
"""
