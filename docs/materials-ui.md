# Material UI — design (parked until approved)

> Goal: choosing and adjusting materials should feel like flipping through a
> **material board**, not editing a settings list. The library
> ([material_library.py](../blender/pipeline/material_library.py), 15 surfaces)
> is now rich enough that the UI is the bottleneck, not the materials.

## Where we are

The N-panel **Materials** list (textured modes only) shows one row per Revit
material: its name + a text dropdown of library surfaces. Choices persist to
`material_overrides.json` next to the bundle. It works, but:

- you pick a surface by **reading a word**, not by seeing the surface;
- the only knob is *which* surface — no tint, no pattern scale, no finish;
- there's no way to answer "which objects have this material?" or "what did
  my Revit materials map to?" without hunting.

## Phase 1 — the material board (swatches + live tweaks)

**Swatch previews.** Render each library surface once onto a lit sample cube
(the matrow technique) at ~200 px and ship them as `media/surfaces/<key>.png`
— same pattern as the mode previews. A dev script regenerates them when the
library changes.

**Visual picker.** Replace the text dropdown with `template_icon_view`
(a `bpy.utils.previews` collection fed by those PNGs): click a material row →
a swatch grid pops for it. The dropdown stays as compact fallback in the row.

**Per-material adjustments** (under the list, for the selected material):

| Knob | Meaning | Plumbing |
|---|---|---|
| Tint | override the Revit colour | replaces `tint` fed to the builder |
| Pattern scale | 0.5×–2× on brick/tile/plank/rib dimensions | multiplier on the mapping node |
| Finish | matte ↔ gloss offset | roughness offset in `build_material` |
| Relief | bump strength multiplier | scales every `_bump` strength |

**Data.** `material_overrides.json` schema v2 — per material id either the old
plain string (v1, surface only, still read) or
`{"surface": "brick", "tint": [r,g,b]|null, "scale": 1.0, "finish": 0.0,
"relief": 1.0}`. Builders grow optional `scale`/`relief` parameters; v1
bundles keep working untouched.

**Mapping audit (Revit side, cheap).** After Load Model, print a small table
in the output window: *Revit material → matched surface* (via
`material_library.category_for`). Answers "why is my feature wall marble?"
in one glance, and teaches users the name-matching rules.

## Phase 2 — selection-aware

- **From selection**: click any object in the viewport → button selects its
  material in the list (objects are named `BIR_Mat_<material_id>` — the
  lookup is free).
- **Isolate toggle**: temporarily grey out everything except the selected
  material's objects ("where is this material?"); restore on toggle off.
- **Apply to similar**: copy this material's overrides onto every material
  whose name shares its matched keyword.

## Phase 3 — palettes (joins the named-style-presets roadmap item)

Save the entire override map as a named **palette** ("Nordic timber",
"Brutalist", "Terracotta town") in `%APPDATA%/blendit/palettes/*.json`;
apply any palette to any project (keyed by matched surface category, not
material id, so palettes transfer between models). Ship two or three starter
palettes. A palette is one JSON file — shareable by design.

## Order + effort

1. **Phase 1** is the value spike: swatch assets (script + one render pass),
   icon-view picker, the four knobs, schema v2 (~a session).
2. **Mapping audit** rides along with Phase 1 (Revit-side, ~30 lines).
3. **Phase 2** next (small, pure live-session).
4. **Phase 3** when style presets get built — same save/load pattern.

Rules that carry over: success feedback passive; camera untouched; overrides
live in the bundle sidecar; every new catalog derives from
`material_library.CHOICES` (single source, locked by test).
