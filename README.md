# Blendit

<p align="center">
  <img src="media/blendit_workflow_readme.gif" alt="Blendit: one click in Revit, rendered in Blender" />
</p>

<p align="center"><b>One click in Revit → your 3D view, rendered in Blender.</b><br>
Free, open source, no subscription.</p>

---

## What is it?

If you've ever tried to make a Revit model look good in Blender, you know the drill:
export the geometry, wrestle the import, rebuild every material by hand, place a
camera, light it… and half an hour later it still looks grey. **Blendit skips all of
that.**

Press one button in Revit and your active 3D view turns up in Blender — framed, lit,
materialled, and rendered, with good-looking defaults out of the box. Then you can
walk away with the image, or hop into Blender to fine-tune the shot.

It runs on **Blender** (also free), so there's nothing to subscribe to and nothing
locking your work in.

<p align="center">
  <img src="media/blendit_hero.png" width="80%" alt="A Blendit line render of a building" />
</p>

## What you get

- 🎨 **Render looks for every purpose** — photoreal, white-card / clay massing, a
  sun-accurate shadow study, and hand-drawn styles: **linework, pen, sketch, cel, and
  hatch**. Pick one on the ribbon; switch live in the review session.
- ☁️ **Atmosphere & weather** — procedural **volumetric clouds** and sky: seven cloud
  types (fair-weather cumulus → overcast → towering storm), a live sun / time-of-day,
  and a 360° storm-ring mode. All procedural — no downloads, no huge sky files.
- ✏️ **Vector export (SVG / PDF)** — any line style exports as true, editable vector
  paths for Illustrator, Inkscape or CAD — not a pixel image.
- 🛬 **Compose your shot** — an interactive review session where you fly around, frame
  the view, straighten your verticals (two-point) or switch to orthographic, tweak the
  light, and snap a capture — all without touching Revit again.
- ⚡ **Fast and repeatable** — the model is cached, so opening it again is instant, and
  it's tuned to stay quick even on big, detailed models.

## Requirements

- **Autodesk Revit** with **[pyRevit](https://github.com/pyrevitlabs/pyRevit)**
  installed (Blendit is a pyRevit extension).
- **[Blender](https://www.blender.org/download/) 4.2 or newer** — a free, separate
  download. Blendit points at it; it doesn't run inside Revit.
- **Windows** (for now).

## Install

> One-click install from pyRevit's **Extensions** manager is on the way — the catalog
> listing is [pending review](https://github.com/pyrevitlabs/pyRevit/pull/3463). Until
> it's merged, use the manual steps below (a one-time setup).

1. **Clone the repo** into a folder that ends in `.extension`:
   ```
   git clone https://github.com/lewismconte/blendit.git Blendit.extension
   ```
   *(No git? Download the ZIP from GitHub and unzip it into a folder named
   `Blendit.extension`.)*
2. In Revit, open **pyRevit → Settings → Custom Extension Directories** and add the
   **parent** folder (the one that *contains* `Blendit.extension`), then **Reload**.
3. A **Blendit** tab appears on the Revit ribbon. Done.

First time you render, Blendit will help you point at your `blender.exe` if it can't
find one (or you can set it under **Settings**).

## Using it

From the **Blendit** ribbon:

1. Open a **3D view** in Revit.
2. **Load Model** — pulls the active view across (the one slow step, with a progress
   bar).
3. Then either:
   - **Open Model** — opens it in Blender to fly around, compose, tweak the look, and
     capture your shot, or
   - **Render Loaded Model** — renders it straight to an image, no fuss.
4. **Open Renders** to find your images.

**Settings** lets you set the Blender path, output folder, default render look, and
quality. That's the whole workflow.

## Where it's going

Blendit works today, and it's built to grow. On the roadmap:

- 🔴 **Live sync** — edit in Revit and watch the Blender view update in real time
  (Enscape-style), streaming only what changed.
- 🌳 **Entourage & assets** — a library of procedural trees, people and cars you can
  scatter into a scene (and round-trip back to Revit as lightweight placeholders).
- 🧱 **Richer materials** — pull real textures and colours from Revit's own material
  and appearance settings.
- 🎬 **Animation** — fly-throughs and turntables.
- 🌅 **HDRI skies** and more lighting options.

## Good to know

- **Blender is a separate, free download** — a one-time setup, then Blendit drives it
  for you.
- **Clouds and photoreal renders look best in Cycles.** For faster Cycles renders,
  turn on your GPU once in Blender's **Preferences → System**. The default EEVEE
  engine is realtime either way.
- **Materials** are a curated set matched to your Revit material names — and you can
  swap any surface live in the review session. (Reading real Revit textures is on the
  roadmap.)
- **Windows only** for now.

## License & credits

**[MIT](LICENSE)** — free to use, free to modify. Blendit drives Blender as a separate
program (it doesn't bundle Blender's code), and ships **no** third-party sky or texture
files, so it stays clean and lightweight.

Built by **[lewismconte](https://github.com/lewismconte)** ·
[portfolio](https://lewismconte.github.io/portfolio). Issues and ideas welcome — if you
put it on a real project, I'd love to hear how it went.

---

## For developers

Blendit is a **bridge**: Revit (IronPython) extracts the active view and writes a small
`.glb` **bundle**; Blender (CPython / `bpy`) imports it and runs a render **pipeline**.
Blender runs as a **separate process**, so nothing heavy loads inside Revit and you keep
full Blender power. The data **contract** between the two sides is the stable seam;
everything else is built on top of it.

- **Deep dive & design rationale:** [CLAUDE.md](CLAUDE.md)
- **The data contract:** [docs/contract.md](docs/contract.md) · **dev loop:**
  [docs/dev-loop.md](docs/dev-loop.md)
- **Parked designs:** [live-sync](docs/live-sync.md) ·
  [live-sync build plan](docs/live-sync-plan.md) · [entourage](docs/entourage.md) ·
  [hatch TAMs](docs/hatch-tam.md)

The tests run **headless under `bpy` — no Revit required**. Render the bundled fixture
without any of Revit:

```
python tests/fixtures/build_fixture.py
blender --background --python blender/headless/render.py -- ^
    --bundle tests/fixtures --out out/render.png ^
    [--engine CYCLES|EEVEE] [--mode MODE] [--samples N] ^
    [--camera perspective|orthographic] [--two-point on|off] [--vector svg|pdf]
```

`MODE`: `realistic`, `white`, `shadow`, `specular`, `linework`, `pen`, `sketch`,
`cel`, `hatch`. All modes at once: `blender --background --python tests/smoke_render.py`.

Verified on Blender 5.0 / 5.1; Blender 4.2 LTS is the intended floor (API differences
are handled at runtime, but treat 4.2 as best-effort until re-verified).
