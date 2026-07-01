"""Demo extraction fallback (IronPython 2.7 safe, no RevitAPI).

Builds the canonical "single box" (plus a glass pane) as schema-conformant dicts
+ MeshData. Real active-3D-view extraction lives in revit_extract.py; this is the
fallback used only when there is no active document (e.g. headless/dev) so the seam
can still be proven end to end. It emits plain dicts (NOT the CPython scene_spec
dataclasses, which can't run under IPy) - the Revit-side mirror of tests/fixtures.
"""
from bir_contract.transport import MeshData


def _box(node, x0, y0, z0, x1, y1, z1, material_id):
    faces = [
        ((0, 0, -1), [(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)]),
        ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
        ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
        ((0, 1, 0), [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)]),
        ((-1, 0, 0), [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)]),
        ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
    ]
    verts, normals, tris = [], [], []
    for normal, corners in faces:
        base = len(verts)
        verts.extend(corners)
        normals.extend([normal, normal, normal, normal])
        tris.append((base, base + 1, base + 2))
        tris.append((base, base + 2, base + 3))
    return MeshData(node, verts, tris, normals=normals, material_id=material_id)


def _quad(node, corners, normal, material_id):
    return MeshData(node, list(corners), [(0, 1, 2), (0, 2, 3)],
                    normals=[normal, normal, normal, normal], material_id=material_id)


def build_demo_bundle():
    """Return (spec_dict, meshes) for the demo box + glass pane."""
    meshes = [
        _box("Box_1", 0.0, 0.0, 0.0, 10.0, 10.0, 10.0, "mat_concrete"),
        _quad("Glass_1",
              [(2.0, -5.0, 0.0), (8.0, -5.0, 0.0), (8.0, -5.0, 8.0), (2.0, -5.0, 8.0)],
              (0.0, -1.0, 0.0), "mat_glass"),
    ]
    spec = {
        "contract_version": "0.1.0",
        "source": {"app": "Revit", "app_version": "", "document": "demo",
                   "active_view": "3D - Demo", "exported_at": ""},
        "units": {"source_unit": "feet", "scale_to_meters": 0.3048, "up_axis": "Z"},
        "coordinate_system": {"project_base_point": [0.0, 0.0, 0.0],
                              "true_north_degrees": 0.0},
        "geometry": {
            "transport": "gltf", "uri": "scene.glb",
            "elements": [
                {"node": "Box_1", "element_id": "1", "category": "Walls",
                 "level": "L1", "material_id": "mat_concrete"},
                {"node": "Glass_1", "element_id": "2", "category": "Curtain Panels",
                 "level": "L1", "material_id": "mat_glass"},
            ],
        },
        "materials": [
            {"id": "mat_concrete", "name": "Concrete - Smooth",
             "base_color": [0.55, 0.55, 0.53], "metallic": 0.0, "roughness": 0.7,
             "transparency": 0.0},
            {"id": "mat_glass", "name": "Glass - Clear",
             "base_color": [0.85, 0.9, 0.9], "metallic": 0.0, "roughness": 0.05,
             "transparency": 0.9, "ior": 1.52},
        ],
        "camera": {"name": "3D - Demo", "type": "perspective",
                   "position": [28.0, -34.0, 16.0], "target": [5.0, 5.0, 5.0],
                   "up": [0.0, 0.0, 1.0], "fov_degrees": 45.0,
                   "two_point_perspective": True},
        "sun": {"mode": "geographic", "latitude": 51.5074, "longitude": -0.1278,
                "date": "2026-06-21", "time": "16:30", "timezone": 1.0,
                "daylight_saving": True, "strength": 1.0, "angle_degrees": 0.526},
        "world": {"sky_type": "nishita", "strength": 1.0,
                  "ground_albedo": [0.3, 0.3, 0.3]},
        "render": {"mode": "realistic", "engine": "CYCLES", "resolution": [960, 540],
                   "samples": 32, "denoise": True, "view_transform": "AgX",
                   "exposure": 0.0},
    }
    return spec, meshes
