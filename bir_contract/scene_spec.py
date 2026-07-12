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

# Single source of truth: transport.py owns CONTRACT_VERSION (it is the IronPython-
# safe module imported by both sides). Re-export it here so the dataclass side and
# the Revit side can never disagree.
from .transport import CONTRACT_VERSION


class Engine(str, Enum):
    CYCLES = "CYCLES"
    EEVEE = "EEVEE"


class RenderMode(str, Enum):
    REALISTIC = "realistic"   # the photoreal default
    WHITE = "white"           # clay / white model
    SHADOW = "shadow"         # sun-accurate shadow study
    LINEWORK = "linework"     # NPR outlines
    SPECULAR = "specular"     # lookdev / reflectivity
    PEN = "pen"               # NPR technical pen
    SKETCH = "sketch"         # NPR hand-drawn sketch
    CEL = "cel"               # NPR anime cel shading
    HATCH = "hatch"           # NPR tonal shadow hatching
    YELLOWTRACE = "yellowtrace"  # NPR loose sketch on yellow trace paper
    KRAFT = "kraft"           # NPR black ink + white accents on brown paper
    BLUEPRINT = "blueprint"   # NPR white line work on cyanotype blue
    DIAGRAM = "diagram"       # NPR flat colour-block poster + heavy outline
    WATERCOLOR = "watercolor"  # NPR loose sepia lines under a warm/cool wash
    RISOGRAPH = "risograph"   # two-tone riso duotone (blue/pink/cream) + keyline


# Canonical list of every render mode -- the SINGLE SOURCE OF TRUTH for the set of
# modes. The JSON schema's render.mode enum and the Blender preset registry are both
# checked against this in tests/, so the three can never silently drift.
RENDER_MODES = tuple(m.value for m in RenderMode)


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
    # --- appearance-asset fields (contract 0.2.0, all optional) ---
    appearance_class: str = ""        # generic|metal|glass|ceramic|stone|masonry|
                                      # concrete|wood|plastic|wallpaint|water|mirror
    glossiness: Optional[float] = None  # raw Revit glossiness 0..1 (roughness = 1-g)
    # Texture maps extracted from the appearance asset. Slots: "diffuse", "bump".
    # Each slot: {"uri": str (bundle-relative, e.g. "textures/brick.jpg"),
    #             "scale_m": [sx, sy] (real-world size of one tile, metres),
    #             "offset_m": [ox, oy], "rotation_deg": float,
    #             "amount": float (bump only)}.
    # Revit gives NO UVs, so the Blender side maps these with real-world box
    # projection (Object coords == metres) - which is how Revit itself maps them.
    maps: Optional[dict] = None


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
    # Two-point perspective keeps verticals vertical (levels the camera). Revit's 3D
    # view is NOT two-point, so this is an opt-in correction, off by default to stay
    # faithful to the view the user framed.
    two_point_perspective: bool = False
    # Framing controls (not extracted from Revit): padding around the model, and a
    # lens shift that slides the frame without tilting (so it preserves two-point).
    framing_margin: float = 1.12
    shift_x: float = 0.0
    shift_y: float = 0.0


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
class Light:
    """An artificial lighting fixture extracted from Revit (contract 0.3.0).

    Photometrics are carried RAW (intensity + its Revit unit, colour temperature)
    so the Blender side owns the watts conversion. Position is in SOURCE units
    (feet) like the camera - the Blender side scales it once on setup. IES
    photometric webs and true line/area emitter shapes are a later addition; the
    `intensity_unit` string and optional fields leave room for them."""
    id: str
    type: str = "point"               # "point" | "spot" | "area"
    position: Vec3 = field(default_factory=lambda: [0.0, 0.0, 0.0])    # source units
    direction: Vec3 = field(default_factory=lambda: [0.0, 0.0, -1.0])  # aim, normalized
    intensity: float = 0.0            # raw Revit value in `intensity_unit`
    intensity_unit: str = ""          # "lm" | "cd" | "lx" | "W" | "" (unknown)
    color_kelvin: Optional[float] = None   # correlated colour temperature
    color: Optional[RGB] = None       # explicit filter colour (linear), if no CCT
    spot_beam_deg: Optional[float] = None   # inner (beam) cone - full angle
    spot_field_deg: Optional[float] = None  # outer (field) cone - full angle
    radius_m: float = 0.05            # emitter soft size -> shadow softness
    on: bool = True                   # fixture switched on / non-zero dimming


@dataclass
class World:
    sky_type: SkyType = SkyType.NISHITA
    hdri_uri: Optional[str] = None    # relative path when sky_type == HDRI
    strength: float = 1.0
    ground_albedo: RGB = field(default_factory=lambda: [0.3, 0.3, 0.3])
    has_site: bool = False            # model brings its own terrain -> no ground plane


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
    lights: list = field(default_factory=list)      # list[Light] (artificial fixtures)
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
