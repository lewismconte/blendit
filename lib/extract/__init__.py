"""Revit-side extraction (RevitAPI, IronPython 2.7 safe) - Phase 1.

Tessellation, materials, camera, and sun extraction from the active 3D view into
schema-conformant dicts + MeshData. Guard all RevitAPI imports so this package
imports cleanly outside Revit. Implemented after contract sign-off.
"""
