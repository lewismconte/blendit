# Build Brief — `Blendit`

This is the governing brief for the repo: a project brief, not a one-shot spec.
Work through it in phases, **confirm the contract before building on it**, and
produce a runnable demo at the end of each phase.

> The long code listings for the contract live in their real files now — see
> [`bir_contract/`](bir_contract/) and [`docs/contract.md`](docs/contract.md). This file
> keeps the narrative, the constraints, and the working agreement.

---

## 1. What we're building

`Blendit` — a tool that moves a Revit model into Blender for
rendering, fast, and applies a curated, good-out-of-the-box rendering pipeline.
The name is a play on "blend it" (Blender + edit); the goal is an experience as
seamless as **Rhino.Inside.Revit** ("one click, it's in Blender, it looks good").

**v1 target:** a one-click Revit-to-Blender rendering tool — press a button in Revit,
get a high-quality render of the current 3D view in Blender, with photoreal
defaults and several render modes.

**But build for more.** v1 is the smallest useful thing; the longer-term aim is a
general Revit↔Blender bridge (live link, asset injection, animation, analysis
viz, and eventually data flowing *back* into Revit). The transport and data
contract must be clean, documented, stable interfaces — everything else is built
on top of them and is expected to change.

---

## 2. Read this before you architect anything

A literal "Blender running inside the Revit process" (the way Rhino.Inside.Revit
loads RhinoCommon into Revit) is **not achievable the same way**:

- Rhino.Inside works because Rhino's core is a **.NET** assembly loadable into a
  .NET host (Revit).
- Blender is **not** .NET. Its `bpy` module is a heavy native CPython module, and
  pyRevit runs on **IronPython**. `bpy` cannot be loaded into Revit's process.

**Therefore the architecture is a bridge, not an in-process embed.** Do **not**
`DllImport` Blender into .NET or `import bpy` inside a pyRevit script. The two
sides are separate processes that talk only through the transport layer (§6).
Keep the door open for tighter coupling later (a future bpy-in-subprocess
"inside" mode), but v1 is a bridge.

> If you ever feel the design requires loading Blender into Revit, **stop and
> flag it** — the design is wrong, not the constraint.

---

## 3. Architecture overview

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│  REVIT  (IronPython)     │         │  BLENDER  (its own process)  │
│  pyRevit extension       │         │  add-on  +  headless bpy     │
│  Extract:                │  bundle │  Import bundle               │
│   • geometry (tessellate)│ ───────▶│  Map materials → Principled  │
│   • materials/appearance │ (glTF + │  Build world (sun + sky/HDRI)│
│   • active-view camera   │  Scene  │  Set camera + view transform │
│   • sun position/time    │  Spec   │  Apply render-mode preset    │
│   • units / base point   │  JSON)  │  Cycles / EEVEE → render PNG │
└─────────────────────────┘         └──────────────────────────────┘
        │                                          ▲
        └────────────  TRANSPORT (pluggable)  ─────┘
        v1: file-based payload + sidecar scene_spec.json in a watched folder
        future: USD · Speckle · websocket live-link
```

The **transport** is the seam. v1 is the simplest thing that works (files on
disk). Everything else is swappable behind the interface.

---

## 4. Tech stack & pinned constraints

**Revit side**
- pyRevit extension — the repo root IS the extension (`Blendit.tab/` + `lib/` at
  the root, so it's pyRevit-catalog-installable). See [`Blendit.tab/`](Blendit.tab/).
- Target **IronPython 2.7** compatibility unless we explicitly opt into the
  CPython engine. Keep Revit-side deps minimal and pure-Python.
- Revit 2025+ requires .NET 8; support a reasonable range of Revit versions.
- Revit API stubs are for IDE hints **only**. Guard RevitAPI imports so the
  package is testable headless.

**Blender side**
- Target **Blender 4.2 LTS and newer** (EEVEE-Next floor). Test on 4.2 LTS and
  the current LTS.
- Package the interactive add-on with the **Blender 4.2+ Extensions** system.
- Headless `bpy`: **one Python version per Blender release** — pin it, document
  it in [README.md](README.md). `bpy`-as-module loads the factory startup scene
  and cannot be `importlib.reload`-ed → fresh process per render, or
  `read_factory_settings(use_empty=True)`.

**Shared**
- Define the data contract once, validatable on both sides: dataclasses
  ([`bir_contract/scene_spec.py`](bir_contract/scene_spec.py)) + JSON schema
  ([`bir_contract/scene_spec.schema.json`](bir_contract/scene_spec.schema.json)).

---

## 5. Repository layout

See [README.md](README.md#repository-layout) for the table. Full intended tree:

The repo root IS the pyRevit extension (`.tab` at root, catalog-installable); the
Blender pipeline + contract ship inside it.

```
blendit/                         # = the extension root (clone as Blendit.extension)
├─ extension.json                # pyRevit catalog metadata
├─ CLAUDE.md  README.md  LICENSE
├─ Blendit.tab/Render.panel/LoadModel.pushbutton/  # ribbon; + OpenModel / RenderLoadedModel
├─ lib/                          # IronPython 2.7-safe Revit-side code (auto on sys.path)
│   ├─ bir_bootstrap · bir_config · bir_export · bir_ui
│   ├─ bir_extract/                  # tessellation, materials, camera, sun
│   └─ bir_transports/gltf/exporter.py
├─ bir_contract/                     # the shared data contract (the seam)
│   ├─ scene_spec.py             # dataclasses (CPython 3 side + tests)
│   ├─ scene_spec.schema.json    # authoritative cross-language schema
│   └─ transport.py              # Exporter/Importer interface (IPy2.7 safe)
├─ blender/
│   ├─ headless/render.py        # bpy entry point: argv → import → pipeline → render
│   ├─ interactive/live.py       # the Open Model session
│   ├─ pipeline/                 # import_bundle · materials · world · camera · look · presets/
│   └─ bir_transports/gltf/importer.py
├─ tests/                        # fixture bundle + headless pipeline tests (no Revit)
└─ docs/                         # contract.md · dev-loop.md
```

---

## 6. The transport layer (the seam — keep it stable)

One interface in [`bir_contract/transport.py`](bir_contract/transport.py):

- `Exporter.export(spec_dict, meshes, out_dir) -> bundle_ref` (Revit side).
- `Importer.load(bundle_ref) -> LoadedScene` (Blender side).

A **Bundle** is a directory whose entry point is `scene_spec.json` (conforms to
the schema), alongside a geometry payload and optional `assets/`. The on-disk
bundle is the real cross-process contract; the classes give each side a stable
shape.

**v1 implementation:** file-based. Revit writes a geometry payload + sidecar
`scene_spec.json` into the model cache; Blender picks it up. The shipped transport
is:
- `gltf` — a self-contained pure-Python binary glTF (`.glb`) writer on the Revit
  side + Blender's native importer on the other. Carries its own axis-conversion
  gotcha (convert Z-up↔Y-up in exactly one place — the exporter). _(An early
  `rawmesh` transport was explored and dropped; glTF won on simplicity + speed.)_

**Future** (don't build, don't preclude): USD/USDZ, Speckle, websocket live link
(pyRevit Routes). The presets, importer, and extractor must not assume glTF.

**Separation of concerns:** a transport moves **geometry + the spec only**.
Materials, world, camera, look, and the render-mode preset are applied afterward
by `pipeline/`. Transport code must not set up shaders or lighting.

---

## 7. Revit side — extraction

From the **active 3D view**, extract into a schema-conformant `spec_dict` +
`list[MeshData]`:
- **Geometry:** tessellate elements to meshes; keep per-element metadata
  (element id, category, level, material ref) for later grouping/override.
- **Materials:** read Revit appearance assets → neutral material records (base
  color, metallic, roughness, transparency, name). Blender does the shader
  mapping (§ materials).
- **Camera:** active view camera → contract `Camera`.
- **Sun:** project sun position (geographic lat/long + date/time preferred;
  azimuth/altitude or vector as fallback).
- **Units & coords:** Revit internal units are **feet**, **Z-up**; Blender is
  **meters**, **Z-up**. Carry feet through the bundle; the Blender importer
  applies ×0.3048 **once**. Carry the project base point for round-trips.
- **Render settings:** chosen mode, engine, resolution.

The pushbutton `script.py` is thin: it calls `lib/bir_extract/` then the active
transport's `export`.

---

## 8. Blender side — render pipeline

A single ordered pipeline, engine-agnostic where possible:

1. Clean scene (`read_factory_settings(use_empty=True)` headless).
2. Import the bundle (geometry via transport; merge the sidecar spec).
3. **Materials:** Revit appearance → Principled BSDF, category-aware
   (metal/glass/mirror/water/emissive distinct), with anti-plastic upgrades.
4. **World:** sun + sky from the `Sun` spec (Sun lamp + Nishita sky or HDRI;
   since 4.2 EEVEE can extract a sun from an HDRI).
5. **Camera:** place from the `Camera` spec; offer two-point perspective
   (vertical correction).
6. **Look:** AgX view transform, sane exposure, light compositor pass (subtle
   bloom/vignette/AO) — most of the polished arch-viz look.
7. Apply the selected render-mode **preset** (§9).
8. **Engine:** Cycles or EEVEE, with samples + denoise.
9. Render PNG (headless) or hand to the interactive viewport.

`tests/` must run steps 2–8 on a hand-written fixture bundle, **no Revit**.

---

## 9. Render modes + Cycles/EEVEE toggle

Render modes are a **data-driven registry** in
[`blender/pipeline/presets/`](blender/pipeline/presets/). Each preset reads the
engine toggle and works in both Cycles and EEVEE. Ship five for v1:

1. **Realistic** *(the photoreal default)* — full PBR, sun + sky/HDRI, AgX, denoise,
   AO, soft shadows, optional slight DoF.
2. **White / Clay** — global white matte override, keep sun + AO.
3. **Shadow study** — sun-accurate clay, shadows emphasized; optional day
   sequence from Revit sun/time.
4. **Linework** — NPR outlines over flat fill (Grease Pencil Line Art and/or
   Freestyle).
5. **Specular / Lookdev** — emphasize specular with a reflective studio HDRI.

**The toggle:** a single `engine` enum (`CYCLES` | `EEVEE`) every preset
respects. EEVEE for fast/interactive; Cycles for accurate finals. Exposed in the
Revit button options and the Blender N-panel.

---

## 10. The "good-by-default" photoreal look

What makes real-time architectural renderers look good by default, mapped to Blender (lives in
`pipeline/look.py`, applied before the per-mode preset so every mode inherits it):
AgX + neutral exposure · sky + sun matched to the Revit sun · AO, soft shadows,
SSR (EEVEE) / accurate GI (Cycles) · two-point perspective + architectural focal
length · subtle bloom + vignette · optional shadow-catcher ground · denoise
(OpenImageDenoise) for Cycles, temporal supersampling for EEVEE.

---

## 11. Build phases

- **Phase 0 — Scaffolding & vertical slice.** Repo + `bir_contract/`; a pyRevit
  button that exports a **single box**; a Blender headless script that imports it
  and renders a flat PNG. Prove the seam end to end.
- **Phase 1 — v1 MVP.** Full extraction → bundle → Blender → **Realistic** preset
  with photoreal defaults. All five modes. Cycles/EEVEE toggle. One-click "Render
  current 3D view." **Ship this.**
- **Phase 2 — Live link.** Interactive EEVEE viewport updating as Revit changes;
  websocket transport (pyRevit Routes); the Blender N-panel UI.
- **Phase 3 — Assets & motion.** Material library; inject Blender assets;
  walkthrough/turntable animation; batch-render multiple views.
- **Phase 4 — "So much more."** USD transport; tighter coupling; analysis data
  toward Revit. *Why* the contract/transport are kept abstract — don't build it
  now, just don't block it.

---

## 12. Guardrails & working agreement

- **Never** load Blender/`bpy` into Revit's process or `DllImport` Blender into
  .NET. Cross-process via the transport only.
- Revit-side code must **import cleanly outside Revit** (guard API imports).
- Keep `bir_contract/` (SceneSpec + transport) **stable and documented**; treat
  changes as deliberate, versioned events. Everything else builds on it.
- Pin the `bpy`/Blender Python version; document it in the README.
- After each phase, deliver a **runnable demo + a short "how to run it" note** for
  the pyRevit dev loop.
- Don't reach for a server dependency (Speckle) or a networked live-link design
  without flagging it first.
- Prefer small, reviewable commits over big drops.
- **Ask before any decision that changes the data contract, the transport
  interface, or the in-process-vs-bridge boundary.**

Environment: Windows + Revit with a pyRevit dev setup; Revit API stubs available;
the `.extension` is wired into pyRevit's Custom Extension Directories and reloaded
to test.

---

## Appendices

The starter contract code (Appendix A), reference material (Appendix B),
transport interface + run model (Appendix C), and the material-mapping spec
(Appendix D) are tracked as their real files / docs:

- **A — SceneSpec contract:** [`bir_contract/scene_spec.py`](bir_contract/scene_spec.py),
  [`bir_contract/scene_spec.schema.json`](bir_contract/scene_spec.schema.json),
  documented in [`docs/contract.md`](docs/contract.md).
- **C — Transport + run model:** [`bir_contract/transport.py`](bir_contract/transport.py),
  the importer/exporter under `blender/transports/` and `lib/bir_transports/`, run
  model in [`docs/dev-loop.md`](docs/dev-loop.md).
- **B & D — references + material mapping:** captured in
  [`docs/contract.md`](docs/contract.md) and to be realized in
  `blender/pipeline/materials.py` during Phase 1.
