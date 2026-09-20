# The data contract (the seam)

The contract is what Revit and Blender agree on. Keep it **stable and
documented**; treat changes as deliberate, versioned events.

## Two representations, one source of truth

| File | Runtime | Role |
|---|---|---|
| [`bir_contract/scene_spec.schema.json`](../bir_contract/scene_spec.schema.json) | both | **Authoritative.** Cross-language JSON Schema (draft 2020-12). |
| [`bir_contract/scene_spec.py`](../bir_contract/scene_spec.py) | CPython 3 (Blender + tests) | Typed convenience representation (dataclasses + enums). |
| [`bir_contract/transport.py`](../bir_contract/transport.py) | IronPython 2.7 **and** CPython 3 | The Exporter/Importer interface + bundle read/write helpers. |

The Revit side runs under **IronPython 2.7**, which has no `dataclasses` — so on
the Revit side, build plain `dict`s that conform to the schema and write JSON.
**Do not import `scene_spec.py` under IronPython.** `transport.py` is kept
IronPython-2.7 safe (no f-strings, no annotations, no dataclasses) so it imports
on both sides.

## Conventions baked in

- **Units:** all linear values are in the **source unit** (Revit feet). The
  geometry payload is exported in the same unit. The Blender importer applies
  `units.scale_to_meters` (0.3048) **once**, to the whole scene — geometry,
  camera, and sun distance together — to avoid double-scaling.
- **Up axis:** **Z** on both sides. `gltf` is natively Y-up, so convert Z-up↔Y-up
  in **exactly one place**: the Revit exporter writes Y-up and Blender's importer
  converts back to Z-up on the way in.
- **Angles:** degrees.
- **Colors:** linear `[r, g, b]` in `0..1`. Only loaded image textures are tagged
  sRGB.

## The bundle

A file-based transport produces a **bundle** directory:

```
my_bundle/
  scene_spec.json   # conforms to the schema; the entry point
  scene.glb         # geometry payload (gltf transport, binary)
  assets/           # optional HDRIs / textures
```

A `bundle_ref` is the path to the directory **or** directly to
`scene_spec.json`. Helpers in `transport.py` (`read_scene_spec`,
`write_scene_spec`, `bundle_dir_of`) resolve both forms.

## Top-level shape of a SceneSpec

| Key | Meaning |
|---|---|
| `contract_version` | semver; major mismatch is refused, minor warns (see `check_contract_version`) |
| `source` | app / version / document / active view / export timestamp |
| `units` | source unit, `scale_to_meters`, up axis |
| `coordinate_system` | project base point, survey point, true north (deg CCW from +Y) |
| `geometry` | `transport`, `uri` (payload, relative to the JSON), `elements[]` (node ↔ Revit metadata) |
| `materials[]` | authoritative material **intent** (Revit appearance approximated) |
| `camera` | active-view camera (position, target, up, FOV/focal, two-point flag) |
| `sun` | geographic (lat/long + date/time) preferred; azimuth/altitude or vector fallback |
| `world` | sky type (nishita/hdri/solid), HDRI uri, strength, ground albedo |
| `render` | mode, engine (CYCLES/EEVEE), resolution, samples, denoise, view transform, exposure |

See the schema for exact types/required fields, and the docstrings in
`scene_spec.py` for per-field intent. An example instance lives in the brief.

## Why keep `materials` / `camera` / `elements` when glTF carries them?

glTF already carries geometry, PBR materials, and (optionally) cameras. The
SceneSpec keeps these anyway as the **authoritative intent**, because (a) glTF's
PBR ≠ Revit's appearance 1:1, and (b) the sidecar lets us re-map / override
without re-exporting. **On import, the SceneSpec is the source of truth and the
geometry payload is just the carrier.**

## Version policy

`CONTRACT_VERSION` is declared in both `scene_spec.py` and `transport.py` and
written into every bundle as `contract_version`.

- **Additive** changes (new optional fields) → bump the **minor** version.
- **Breaking** changes (rename/remove/retype, new required field) → bump the
  **major** version; `check_contract_version` refuses cross-major bundles.

Keep both declarations and this doc in sync when the contract moves.

## Contract 0.2.0 — real material appearance (SHIPPED)

The Appendix-D material iteration. The `Material` record gained three **optional**
fields (additive → minor bump 0.1.0 → 0.2.0; 0.1.0 bundles still load, with a
console note):

| Field | Type | Meaning |
|---|---|---|
| `appearance_class` | string | `generic·metal·glass·mirror·water·ceramic·stone·masonry·concrete·wood·plastic·wallpaint` — coarse class from the asset's schema (drives e.g. the metallic hint) |
| `glossiness` | number 0..1 \| null | raw Revit glossiness; roughness = 1 − glossiness when present |
| `maps` | object \| null | texture maps: `{"diffuse": map, "bump": map}` |

Each map: `{"uri": "textures/<file>", "scale_m": [sx, sy], "offset_m": [ox, oy],
"rotation_deg": a, "amount": b}` (`amount` bump only). The **producer**
(`bir_extract/appearance.py`) walks the Revit appearance asset
(`AppearanceAssetElement.GetRenderingAsset()` → connected `UnifiedBitmap`s) and
emits absolute `source_path`s; the **glTF exporter** copies those files into the
bundle's `textures/` dir (deduped) and rewrites them to bundle-relative `uri`s —
a `source_path` never reaches disk. The **consumer**
(`blender/pipeline/materials.py`) box-projects the bitmaps on Object coordinates
at `scale_m`: Revit gives no UVs, and its own mapping is real-world box
projection, so this reproduces it exactly (merge guarantees Object == world
metres). A material whose asset can't be read falls back to the graphics-shading
approximation + the curated library, as before.

## Material identity vs. view display (producer-side, no contract change)

Extraction is WYSIWYG — `view_export.py` walks the view with `CustomExporter`,
`geometry.py` sets `Options.View` — so Revit reports the material the **view
displays**, not the one **assigned to the element**. Those differ whenever the
view carries *phase graphic overrides* (`Manage → Phases → Graphic Overrides` has
a Material column, populated in most office templates): Revit substitutes the
phase's override material, and the bundle ends up full of materials named
"Phase - New" / "Existing" instead of "Brick - Buff" — flat, wrong, and invisible
to the name-keyword matching in `blender/pipeline/material_library.py`.

`bir_extract/element_materials.py` repairs this before the keys become
`MeshData`, on **both** geometry paths. The rule is mechanism-agnostic on
purpose — it never names phases:

1. If the view reported **two or more** materials for the element, do nothing.
   Substitution is per-element and all-or-nothing, so a preserved multi-material
   split proves there was no substitution. This guard is also what keeps the
   heuristic from mangling elements whose materials come from somewhere
   `GetMaterialIds` under-reports.
2. Otherwise ask the element what it owns — compound-structure layers, instance
   and type `GetMaterialIds`, paint, `STRUCTURAL_MATERIAL_PARAM`, the category
   material. If the reported material is in that set it is genuine → keep it.
3. If it is not, rewrite it to the element's own material. **Exact** when the
   element owns one; when it owns several the override already collapsed the
   per-face split irrecoverably, so the primary is used (outermost
   compound-structure layer first — the face a renderer mostly sees) and counted
   as *approximate*.
4. If the element owns nothing better, keep the view's material — it at least
   renders as something.

Cost on a model with no overrides: one `GetTypeId()` and a dict hit per element
(the owned-material set is cached per element type, namespaced by the link's
material prefix). The repair logs a one-line summary with the exact/approximate
counts; `BLENDIT_MATERIAL_REPAIR=0` disables it.

**Not fixed by this, by design:** materials that are genuinely assigned but badly
*named* — imported CAD and DirectShape content whose materials Revit auto-creates
as `Render Material 128-128-128`. Those really are the element's own material,
so there is nothing better to resolve to; making them render well is a
Blender-side concern.
