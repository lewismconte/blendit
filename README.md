# Blendit

<p align="center">
  <img src="media/blendit_workflow_readme.gif" alt="Blendit: one click in Revit, rendered in Blender" />
</p>

> One click in Revit → the current 3D view, in Blender, looking good.

An open-source, one-click renderer built as a **bridge** between Revit and
Blender (not an in-process embed — see [why](CLAUDE.md#2-read-this-before-you-architect-anything)).
Press a button in Revit; get a high-quality render of the active 3D view in
Blender with curated, good-out-of-the-box defaults and several render modes.

The name is a play on "blend it" (Blender + edit), aiming for the same seamless
feel as **Rhino.Inside.Revit**. v1 is the smallest useful thing; the architecture
is built so the longer-term aim (live link, asset injection, animation, data back
into Revit) drops in behind a stable seam.

## Architecture in one line

Revit (IronPython) **extracts** the active view → a **transport** writes a
**bundle** (geometry payload + `scene_spec.json`) → Blender (CPython `bpy`)
**imports** it and runs a render **pipeline**. The transport is the seam;
everything else is built on top of it and is expected to change.

```
REVIT (IronPython 2.7)  ──bundle──▶  BLENDER (CPython 3 / bpy)
  extract + export                     import + pipeline + render
              └──────── TRANSPORT (pluggable) ────────┘
```

## Status

**Working end to end on real models, verified on Blender 5.0.** One click in Revit
extracts the active 3D view, writes a binary glTF (`.glb`) bundle, and Blender
imports + renders it through the pipeline. What's built:

- **Real extraction** — geometry (tessellated, grouped per material), materials,
  active-view camera, and project sun, from the active 3D view.
- **8 render modes** — Realistic, White / Clay, Shadow, Specular, plus four NPR
  modes: Linework, Pen, Sketch, Cel (Grease Pencil Line Art + toon shading).
- **Vector export (SVG / PDF)** — in any line mode, export the Line Art as true
  scalable vector paths (Illustrator / Inkscape / CAD-ready), camera-projected to
  match the composed frame. From the Open Model panel or the headless `--vector`
  flag. (cel exports outlines only — its colour bands are raster.)
- **Cycles / EEVEE toggle**, samples, denoise, resolution, quality presets — all
  driven from the Revit ribbon.
- **Camera & framing** — auto-fits the model from the Revit view angle. In Open
  Model a single **Projection** dropdown switches Perspective / **Two-Point** (level
  the camera so verticals stay vertical, tilt-shift in place) / **Orthographic**
  without throwing away your composition, plus manual focal-length and lens-shift
  controls. Two-point is off by default to stay faithful to the framed Revit view.
- **Explicit, honest workflow** — **Load Model** extracts the active 3D view (the
  one slow step, with a progress bar); **Open Model** opens it in an interactive
  Blender session (stripped "Fly" review UI, live Look + per-mode sliders, WYSIWYG
  framing, capture-to-PNG); **Render Loaded Model** renders it headless as-is. You
  can't open or render until you've loaded.
- **Fast + cached** — binary `.glb` transport, a per-model bundle cache, and a
  prepared-`.blend` scene cache so repeat opens skip re-extraction and re-import.
  Imported geometry is merged by material (one object per material), making Line
  Art and rendering 5–14× faster on detailed models.

Not yet: a true live websocket link (re-run **Load Model** to refresh after model
edits for now), richer materials from Revit appearance assets (contract 0.2.0),
an entourage / asset library, and animation. See
[CLAUDE.md §11](CLAUDE.md#11-build-phases) for the phase plan.

## Repository layout

The repo root **is** the pyRevit extension (`.tab` at the root, so it's
catalog-installable). The Blender pipeline and the shared contract ship inside it.

| Path | What |
|---|---|
| `Blendit.tab/` | The Render ribbon: Load Model · Open Model · Render Loaded Model · Mode · Quality · Resolution · Engine · Open Renders · Settings |
| `lib/` | IronPython-2.7 Revit side (auto-added to `sys.path` by pyRevit): extraction, glTF exporter, config, cache keys, shared UI |
| `contract/` | The seam — `scene_spec.py` (typed, CPython), `scene_spec.schema.json` (authoritative), `transport.py` (IronPython-2.7 safe, both sides) |
| `blender/` | `transports/` (glTF importer), `pipeline/` (import · merge · materials · world · camera · look · ground · engine · npr · cache + `presets/`), `interactive/` (Open Model session), `headless/` (render entry point) |
| `extension.json` | pyRevit catalog metadata |
| `tests/` | Fixture-based pipeline tests that run headless under `bpy` — **no Revit required** |
| `docs/` | [`contract.md`](docs/contract.md) (the data contract), [`dev-loop.md`](docs/dev-loop.md) (how to run it) |

## Pinned constraints

- **Revit side:** IronPython 2.7 compatible, pure-Python, no heavy native deps in
  process. RevitAPI imports are guarded so the package imports cleanly headless.
- **Blender side:** target **Blender 4.2 LTS and newer** (EEVEE-Next floor).
  Package the interactive add-on with the **4.2+ Extensions** system.
- **Headless `bpy`:** one Python version per Blender release — pin the `bpy`
  wheel to the target Blender's CPython. `bpy`-as-module loads the factory
  startup scene and cannot be reloaded → fresh process per render, or
  `read_factory_settings(use_empty=True)`.
- **Developed and verified on Blender 5.0.** 4.2 LTS is the intended floor but
  is **not yet retested** on this build — API churn is handled at runtime where it
  bit (the physical-sky enum `NISHITA` → `MULTIPLE_SCATTERING` in 5.0, and the EEVEE
  engine id, are both resolved dynamically), but treat 4.2 as best-effort until
  re-verified. _(Pin the exact CI `bpy` wheel here once chosen.)_
- **Windows only** for now — the Revit side and the shell/path handling assume
  Windows (the platform Revit + pyRevit run on).

## Known limitations

Honest gaps in this release (none block a one-click render; all are on the
roadmap):

- **Sky is physical (Nishita) or solid** — HDRI-based lighting isn't wired yet.
- **Cycles renders on CPU by default** — for fast High/Final renders, enable a GPU
  in Blender's Preferences → System once. EEVEE (the default) is realtime regardless.
- **Materials** use a curated procedural library matched to the Revit material name
  (overridable in the interactive N-panel); reading real textures from Revit
  appearance assets is a later contract revision.

## Running it

**Render the fixture (no Revit needed)** — regenerate the bundle and render it:

```
python tests/fixtures/build_fixture.py
blender --background --python blender/headless/render.py -- ^
    --bundle tests/fixtures --out out/render.png ^
    [--engine CYCLES|EEVEE] [--mode MODE] [--samples N] ^
    [--camera perspective|orthographic] [--two-point on|off]
```

`MODE`: realistic, white, shadow, specular, linework, pen, sketch, cel, hatch.
`--two-point on` levels the camera so verticals stay vertical (off by default).

**Vector line drawing:** add `--mode pen --vector svg` (or `pdf`) to write a
scalable `.svg` / `.pdf` instead of a PNG (line modes only; the `--out` extension
is swapped automatically).

**All modes at once:** `blender --background --python tests/smoke_render.py`

**Install in Revit (manual):** pyRevit recognises an extension by the `.extension`
folder suffix, so clone this repo into a folder named `Blendit.extension`:
```
git clone https://github.com/lewismconte/blendit.git Blendit.extension
```
then add that folder's **parent** as a pyRevit Custom Extension Directory and reload.
(Once listed in the pyRevit extensions catalog, the extension manager handles this
for you.) Use the **Blendit → Render** ribbon. The flow is explicit: **Load Model**
extracts the active 3D view (the one slow step, with a progress bar), then **Open
Model** opens it in interactive Blender (snap your shots there) or **Render Loaded
Model** renders it headless as-is — you can't open or render until you've loaded.
If Blender isn't installed, the buttons prompt you to download it or point at an
existing `blender.exe` (or set `BLENDIT_BLENDER_EXE`). Settings live in
`%APPDATA%\blendit\` and the per-model cache in `%LOCALAPPDATA%\blendit\`. Full
pyRevit dev loop in [docs/dev-loop.md](docs/dev-loop.md).

## License

[MIT](LICENSE). Blendit bridges Blender as a **separate process** — it does not
bundle or link `bpy` — so Blender's GPL does not extend to this code. Surface
textures are **procedural** (built from Blender's native texture nodes), so the
repo ships **no** third-party image/HDRI assets and stays licence-clean.
