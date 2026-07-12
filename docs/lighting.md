# Artificial lighting (design note)

> **Status: v1 BUILT (contract 0.3.0).** Revit lighting fixtures are extracted
> WYSIWYG and rebuilt as functional Blender lamps, so interiors light up instead
> of rendering black. IES photometric webs and true line/area emitter shapes are
> deferred (the contract leaves room for them).

## Why

The bundle carried geometry, materials, camera, and the sun - but no artificial
lights. Interior views therefore rendered black/flat, lit only by whatever sky
leaked through openings, even though Revit models routinely carry real
photometric fixtures. This translates those fixtures so a room reads.

## Extraction (Revit side)

WYSIWYG, reusing the `CustomExporter` walk that already extracts geometry:

- `view_export.py OnLight(node)` (was a `pass` stub) records every **displayed**
  light - the exporter only calls it for fixtures the view actually shows, so
  visibility rules (hidden fixtures, categories, links) are respected for free.
  It captures the fixture's world placement (the composed instance/link
  transform) + element ref, mirroring the RPC-proxy pattern (record in the
  callback, resolve afterwards).
- `lights.py resolve_lights()` reads photometrics off each fixture element via
  `BuiltInParameter` - the `FBX_LIGHT_*` family. **Verified enum names**
  (Revit's own, including the API's misspelling `FBX_LIGHT_LIMUNOUS_FLUX`):
  luminous flux / illuminance / intensity / wattage for brightness,
  `FBX_LIGHT_INITIAL_COLOR_TEMPERATURE` for colour, `FBX_LIGHT_SPOT_BEAM_ANGLE`
  / `..._FIELD_ANGLE` for the cone. Every read is guarded and candidate-listed
  (`getattr` skips names a given Revit version lacks); a fixture that yields
  nothing still emits a default point light so it never silently vanishes. A
  concise per-light log line prints on extraction so the real values/units
  surface on the first live run.
- `extract_lights_collector()` is the fallback (host `OST_LightingFixtures` in
  the view) for the 2D / non-CustomExporter path and as a safety net.
- Point vs spot is inferred from the presence of a spot cone. Position is in
  source feet (like the camera); the Blender side scales once.

Contract: a new optional `lights` array (`Light` dataclass) - additive, so old
bundles still load (minor version bump 0.2.0 -> 0.3.0 only warns). Carries RAW
intensity + its unit so the Blender side owns the watts conversion; IES/line/
area fields can be added later without breaking anything.

## Consumption (Blender side)

`pipeline/lights.py setup_lights(spec, scale)` builds a `BIR_Lights` collection
(one POINT/SPOT lamp per fixture), placed in metres, coloured from the colour
temperature (`_kelvin_to_rgb` blackbody approximation), spot cone from
beam/field. Runs in `prepare_scene` after the ground, before the preset -
lifecycle identical to the sun lamp (built fresh each session, past the .blend
cache boundary, idempotent so a live mode-switch never stacks lamps).

**Intensity is normalized, not physically absolute.** Revit intensity comes in
mixed units (cd/lm/lx/W) and Blender lamp energy is radiant watts; exactly like
`world._SUN_GAIN` is an empirical key gain, `_GAIN` maps each unit to watts with
a constant tuned to light a typical room, clamped, and dialled by the Live
"Lights Strength" multiplier. Absolute photometric accuracy is a v2 concern.

**Per-mode gating with a universal toggle.** Lit modes (realistic/specular) show
the fixtures by default; drawing/clay modes hide them (interior lamps would wash
out the sun-derived Shader-to-RGB tone those looks depend on). A single choke
point in `prepare_scene` applies the default (`lights.DEFAULT_ON_MODES`); Live
View's **Artificial Lights** panel exposes a master toggle + strength in EVERY
mode, overriding the default in-session, and the checkbox re-seeds from the mode
default on each switch so it never lies.

## Verification

`tests/headless_lights.py`: the fixture's two lights (a warm point + a cool
spot) become the right lamp types at metre positions with correct colours;
lit-mode default shows them, a drawing mode hides them, the master toggle +
strength work, and - the point of the feature - a lit-vs-unlit render is
measurably brighter. `tests/fixtures/build_fixture.py` carries the `lights`
section; `smoke_render` renders all modes with lights present.

The **extraction** can only be finished against a real model (the exact
`FBX_LIGHT_*` values/units vary by fixture family and Revit version) - re-run
Load View on an interior model in Revit and read the printed per-light log, the
established "iterate on real tracebacks" pattern.

## v2 hooks (noted, not built)

IES photometric webs (ship as bundle files via the exporter's
`_copy_texture_maps` pattern, load into spot lights); true line/area emitter
geometry; physically absolute intensity; interior auto-exposure.
