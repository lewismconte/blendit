"""Generate the test-fixture bundle (a box + a glass pane) with NO Revit/Blender.

Builds MeshData by hand, runs them through the REAL glTF exporter, and writes
`scene_spec.json` + `scene.glb` next to this file. Re-run to regenerate:

    python tests/fixtures/build_fixture.py

Coordinates are Revit-native: feet, Z-up. The exporter converts to glTF Y-up.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_REVIT_LIB = os.path.join(_ROOT, "lib")
for p in (_ROOT, _REVIT_LIB):
    if p not in sys.path:
        sys.path.insert(0, p)

from contract.scene_spec import (  # noqa: E402
    SceneSpec, Source, Units, CoordinateSystem, Geometry, Element, Material,
    Camera, Sun, World, RenderSettings, Engine, RenderMode, SkyType, CameraType,
)
from contract.transport import MeshData, get_exporter  # noqa: E402
import transports.gltf.exporter  # noqa: E402,F401  (registers the "gltf" exporter)


def _box(node, x0, y0, z0, x1, y1, z1, material_id):
    """A closed box as 24 verts (4 per face) with per-face normals, 12 tris."""
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
        normals.extend([normal] * 4)
        tris.append((base, base + 1, base + 2))
        tris.append((base, base + 2, base + 3))
    return MeshData(node, verts, tris, normals=normals, material_id=material_id)


def _quad(node, corners, normal, material_id):
    """A single rectangle (e.g. a glass pane): 4 verts, 2 tris."""
    verts = list(corners)
    normals = [normal] * 4
    tris = [(0, 1, 2), (0, 2, 3)]
    return MeshData(node, verts, tris, normals=normals, material_id=material_id)


def build_spec():
    spec = SceneSpec(
        source=Source(app="Fixture", app_version="0", document="fixture",
                      active_view="3D - Fixture", exported_at="2026-06-24T00:00:00Z"),
        units=Units(),
        coordinate_system=CoordinateSystem(),
        geometry=Geometry(
            transport="gltf", uri="scene.glb",
            elements=[
                Element(node="Box_1", element_id="1", category="Walls",
                        level="L1", material_id="mat_concrete"),
                Element(node="Glass_1", element_id="2", category="Curtain Panels",
                        level="L1", material_id="mat_glass"),
            ],
        ),
        materials=[
            Material(id="mat_concrete", name="Concrete - Smooth",
                     base_color=[0.55, 0.55, 0.53], metallic=0.0, roughness=0.7,
                     transparency=0.0),
            Material(id="mat_glass", name="Glass - Clear",
                     base_color=[0.85, 0.9, 0.9], metallic=0.0, roughness=0.05,
                     transparency=0.9, ior=1.52),
        ],
        camera=Camera(name="3D - Fixture", type=CameraType.PERSPECTIVE,
                      position=[28.0, -34.0, 16.0], target=[5.0, 5.0, 5.0],
                      up=[0.0, 0.0, 1.0], fov_degrees=45.0,
                      two_point_perspective=False),
        sun=Sun(mode="geographic", latitude=51.5074, longitude=-0.1278,
                date="2026-06-21", time="16:30", timezone=1.0,
                daylight_saving=True, strength=1.0, angle_degrees=0.526),
        world=World(sky_type=SkyType.NISHITA, strength=1.0,
                    ground_albedo=[0.3, 0.3, 0.3]),
        render=RenderSettings(mode=RenderMode.REALISTIC, engine=Engine.CYCLES,
                              resolution=[960, 540], samples=32, denoise=True,
                              view_transform="AgX", exposure=0.0),
    )
    return spec.to_dict()


def main():
    meshes = [
        _box("Box_1", 0.0, 0.0, 0.0, 10.0, 10.0, 10.0, "mat_concrete"),
        _quad("Glass_1",
              [(2.0, -5.0, 0.0), (8.0, -5.0, 0.0), (8.0, -5.0, 8.0), (2.0, -5.0, 8.0)],
              (0.0, -1.0, 0.0), "mat_glass"),
    ]
    spec = build_spec()
    ref = get_exporter("gltf").export(spec, meshes, _HERE)
    print("wrote bundle:", ref)
    print("  payload:   ", os.path.join(_HERE, spec["geometry"]["uri"]))


if __name__ == "__main__":
    main()
