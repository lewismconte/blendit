"""Blendit - shared scene contract (typed, CPython 3 side).

The JSON schema (scene_spec.schema.json) is the authoritative cross-language
contract. This module is the convenience representation for the Blender add-on,
the headless renderer, and the tests. DO NOT import this under IronPython 2.7 -
the Revit side emits schema-conformant dicts/JSON instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

CONTRACT_VERSION = "0.1.0"


class Engine(str, Enum):
    CYCLES = "CYCLES"
    EEVEE = "EEVEE"


class RenderMode(str, Enum):
    REALISTIC = "realistic"   # the photoreal default
    WHITE = "white"           # clay / white model
    SHADOW = "shadow"         # sun-accurate shadow study
    LINEWORK = "linework"     # NPR outlines
    SPECULAR = "specular"     # lookdev / reflectivity


class SkyType(str, Enum):
    NISHITA = "nishita"       # physical sky driven by the sun
    HDRI = "hdri"             # image-based lighting
    SOLID = "solid"           # flat color (fast / diagram)


class CameraType(str, Enum):
    PERSPECTIVE = "perspective"
    ORTHOGRAPHIC = "orthographic"


Vec3 = list  # [float, float, float]
RGB = list   # [float, float, float] linear 0..1


@dataclass
class Units:
    source_unit: str = "feet"
    scale_to_meters: float = 0.3048   # applied once on import to the whole scene
    up_axis: str = "Z"


@dataclass
class CoordinateSystem:
    project_base_point: Vec3 = field(default_factory=lambda: [0.0, 0.0, 0.0])
    survey_point: Optional[Vec3] = None
    true_north_degrees: float = 0.0   # CCW from +Y; feeds Blender's North Offset


@dataclass
class Source:
    app: str = "Revit"
    app_version: str = ""
    document: str = ""
    active_view: str = ""
    exported_at: str = ""             # ISO 8601 UTC


@dataclass
class Material:
    """Authoritative material *intent*, approximated from the Revit appearance
    asset. The Blender side maps this to a Principled BSDF (and may override the
    glTF's own material)."""
    id: str
    name: str = ""
    base_color: RGB = field(default_factory=lambda: [0.8, 0.8, 0.8])
    metallic: float = 0.0
    roughness: float = 0.5
    transparency: float = 0.0         # 0 opaque .. 1 fully transparent (glass)
    ior: float = 1.45
    emissive: Optional[RGB] = None
    emissive_strength: float = 0.0


@dataclass
class Element:
    """Maps a node in the geometry payload (by name) back to Revit metadata, so
    the Blender side can group / override by category, level, etc."""
    node: str                         # glTF node name (stable key into the payload)
    element_id: str = ""
    category: str = ""                # e.g. "Walls", "Glazing", "Roofs"
    family: str = ""
    type_name: str = ""
    level: str = ""
    material_id: Optional[str] = None


@dataclass
class Geometry:
    transport: str = "gltf"           # which transport produced the payload
    uri: str = "scene.glb"            # relative path to the payload (next to the JSON)
    elements: list = field(default_factory=list)   # list[Element]


@dataclass
class Camera:
    name: str = "RevitView"
    type: CameraType = CameraType.PERSPECTIVE
    position: Vec3 = field(default_factory=lambda: [0.0, 0.0, 0.0])     # source units
    target: Vec3 = field(default_factory=lambda: [0.0, 1.0, 0.0])      # look-at point
    up: Vec3 = field(default_factory=lambda: [0.0, 0.0, 1.0])
    fov_degrees: float = 45.0         # perspective
    ortho_scale: Optional[float] = None
    focal_length_mm: Optional[float] = None
    sensor_mm: float = 36.0
    clip_start: float = 0.1
    clip_end: float = 10000.0
    two_point_perspective: bool = True   # keep verticals vertical (architectural)


@dataclass
class Sun:
    """Prefer `geographic` (lat/long + date/time) and let Blender's Sun Position
    add-on compute azimuth/altitude AND sync a Sky Texture. Fall back to an
    explicit azimuth/altitude if the Revit sun is set manually."""
    mode: str = "geographic"          # "geographic" | "direct" | "vector"
    # geographic
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    date: Optional[str] = None        # "YYYY-MM-DD"
    time: Optional[str] = None        # local "HH:MM"
    timezone: Optional[float] = None  # UTC offset hours
    daylight_saving: bool = False
    # direct / vector fallbacks
    azimuth_degrees: Optional[float] = None
    altitude_degrees: Optional[float] = None
    direction: Optional[Vec3] = None  # normalized, points FROM sun TO scene
    # appearance
    strength: float = 1.0
    angle_degrees: float = 0.526      # sun disk size -> shadow softness
    color: Optional[RGB] = None


@dataclass
class World:
    sky_type: SkyType = SkyType.NISHITA
    hdri_uri: Optional[str] = None    # relative path when sky_type == HDRI
    strength: float = 1.0
    ground_albedo: RGB = field(default_factory=lambda: [0.3, 0.3, 0.3])


@dataclass
class RenderSettings:
    mode: RenderMode = RenderMode.REALISTIC
    engine: Engine = Engine.CYCLES
    resolution: list = field(default_factory=lambda: [1920, 1080])
    samples: int = 128
    denoise: bool = True
    film_transparent: bool = False
    view_transform: str = "AgX"
    exposure: float = 0.0


@dataclass
class SceneSpec:
    contract_version: str = CONTRACT_VERSION
    source: Source = field(default_factory=Source)
    units: Units = field(default_factory=Units)
    coordinate_system: CoordinateSystem = field(default_factory=CoordinateSystem)
    geometry: Geometry = field(default_factory=Geometry)
    materials: list = field(default_factory=list)   # list[Material]
    camera: Camera = field(default_factory=Camera)
    sun: Sun = field(default_factory=Sun)
    world: World = field(default_factory=World)
    render: RenderSettings = field(default_factory=RenderSettings)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SceneSpec":
        # Shallow rebuild is enough for the starter; tighten with a real
        # (de)serializer (e.g. pydantic / cattrs) once the contract settles.
        spec = cls()
        for k, v in d.items():
            if hasattr(spec, k):
                setattr(spec, k, v)
        return spec
