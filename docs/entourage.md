# Entourage — parametric library (design doc, parked)

> **Status: draft / parked.** This is a vision + architecture note, not committed
> work. Nothing here is built yet. Keep it in the pocket; develop or trim later.
> The thesis was de-risked by two working prototypes (see *Prior art* below).

## The idea

Entourage — the trees, shrubs, scale figures, street furniture that populate an
architectural render or drawing — is normally either **flat PNG cut-outs** or
**gigabytes of static 3-D assets**. Both repeat visibly (the "same tree pasted
five times" tell) and neither plays nicely with non-photoreal output.

Store the **recipe, not the mesh**. A *species* + a *seed* + a few sliders
generates a unique instance every time. A row of 30 street trees is 30 seeds, not
30 imported models. And because it is real geometry, it flows straight into
Blendit's existing render modes — **including the Line Art / SVG path** (see
[npr.py](../blender/pipeline/npr.py)). That is the unlock:

> **Parametric trees that come out as vector linework in your drawings.**

Why parametric beats an asset library:

- Infinite variation, zero visible repetition.
- Tiny footprint — a few bytes of params + a seed vs. GB of meshes.
- Resolution / LOD on demand.
- One stylistic treatment — entourage inherits the active render mode (photoreal
  *or* pen / sketch / linework / SVG).
- Editable in place by **age**, **season**, species variant.

## Prior art (already proven, in `08_Generators_and_Scripts/`)

Two standalone HTML/three.js generators already prove both output branches:

- `eucalyptus_tree_generator.html` — recursive L-system + phyllotaxis + pipe
  model, **OBJ + MTL export**.
- `eucalyptus_v8_11.html` — the mature one: 6 botanical branching patterns
  (phyllotaxis / whorled / alternate / tristichous / monopodial / sympodial),
  growth-stage presets (sapling → young → established → mature, **same seed =
  one tree aging**), a marching-cubes "blob" canopy, an **ink mode** (inverted
  hull outline), and a **camera-projected SVG outline export**.

The two genuinely hard parts of that prototype — the blob isosurface and the ink
outline — are **native features** in Blender (metaballs; the Line Art modifier
Blendit already uses). So the port is more "port + delete code" than rewrite.

## Architecture — mirror the render-mode registry

The `RENDER_MODES` single-source-of-truth pattern (locked by `tests/`) is the
template. Each species is a module exposing a parameter schema + a
`build(seed, params) -> object`, registered in one canonical tuple so it is
test-locked and cannot drift.

```
blender/entourage/
  registry.py          # SPECIES tuple — single source of truth (test-locked, like RENDER_MODES)
  base.py              # Species: param schema + build(seed, params) -> object
  generate.py          # recursive skeleton builder (port of the JS branch())
  foliage.py           # leaf-card instancing + metaball canopy ("blob")
  scatter.py           # place N along a curve / on a surface, per-instance seed
  species/
    eucalyptus.py      # the v8_11 generator, ported
    deciduous.py  conifer.py  palm.py  shrub.py  grass.py
    person_scale.py    # low-poly / silhouette scale figure
```

A test mirrors `test_contract.py` / `headless_register.py`: assert the species
registry == the documented species set, and that every species' param schema is
complete.

## Engine — Geometry Nodes, with a Python skeleton for the hard recursion

**Recommended: hybrid.**

- **Trunk + branches:** build a **curve skeleton** in Python (one spline per
  branch, radius per point = pipe model). Direct port of the JS recursion; true
  branching recursion is awkward in pure Geometry Nodes. Curves are lighter than
  cylinders *and* feed Line Art / SVG natively.
- **Scatter + instancing + foliage:** **Geometry Nodes**. Instance-on-points for
  leaf cards; GN handles the "30 trees along this curve, each transformed +
  seeded" problem far better than Python duplication.

The alternative — full Geometry Nodes including the recursion via Repeat Zones —
is more elegant but materially more work, and the recursion is the fiddly part.
Start hybrid; migrate the skeleton to GN later if it earns its keep.

### The UX principle that makes GN safe to introduce

A **node group's exposed inputs render automatically as plain sliders** in
Blender's UI. The user never has to see the node graph. So GN is the engine and
the user sees only "Age / Season / Density." Introducing them to Geometry Nodes
becomes **progressive disclosure**, not a cliff.

> Note: **Geometry Nodes drives geometry; textures are driven by *shader* node
> groups.** Different editors, same trick — both expose their inputs as sliders.
> The "tweak textures too" idea is real, it is just a shader node group, not GN.

## UX — a selection-aware Inspector panel (not a popup)

**Decision: a selection-aware "Inspector" section in the existing Blendit N-panel.
Not a modal popup.**

Why not a popup: modal dialogs are for **one-shot commands** (confirm, pick a
file). They block the viewport, so you cannot drag a slider and watch the result.
Parametric tweaking is inherently iterative — drag → watch → drag. A panel
supports that loop and gets out of the way when unused.

Behaviour:

- Click a **tree** → the panel shows that tree's growth params.
- Click a **wall** → the panel shows that material's texture params.
- This is exactly how Blender's own Properties editor behaves — idiomatic to
  anyone who has touched Blender, friendly to anyone who has not.
- **Folds in the existing per-material override UI** ([live.py](../blender/interactive/live.py),
  `BIR_UL_materials`) — one consistent Inspector instead of a second panel.
- **Progressive disclosure:** an optional `Edit nodes ▸` button opens the real
  GN / shader graph for power users. Off the default path.

So the same Inspector surfaces **both** entourage geometry params and material /
texture params, even though one is GN and the other is shader nodes.

## JS → Blender port map

| `v8_11` (three.js) | Blender port | Note |
|---|---|---|
| `mulberry32(seed)` | `random.Random(seed)` | deterministic — same seed, same tree |
| recursive `branch()` + pipe model | curve skeleton (spline per branch, radius per point) | lighter; feeds Line Art + SVG |
| `getAz()` branching patterns | direct port | phyllotaxis / whorled / etc. carry over |
| flat leaf cards | GN instance-on-points | cheap; reads well in NPR |
| marching-cubes blob canopy | **native metaballs / Points→Volume→Volume-to-Mesh** | do not port the MC code |
| ink mode (inverted hull) | **already in `npr.py`** (Line Art) | free; pipeline traces entourage too |
| `exportSVG()` camera projection | GP→SVG path, or port the projector to Python | working algorithm already exists |

## Randomization & variation axes

The growth presets generalise into axes every species shares:

- **Scatter seed** → derives a per-instance seed → each instance jittered within
  its param ranges. Reproducible: same scatter seed = same forest. One `Reroll`
  button; `pin` to lock a hero and reroll the rest.
- **Age** — the growth stages, constant-seed = *the same tree aging*.
- **Season** — foliage density + colour ramp (bare / autumn / summer).
- **Species variant** — presets per real tree (Eucalyptus, London Plane, Oak,
  Birch, Pine, Palm): a param pack + branching pattern + leaf shape + bark colour.

## Blendit integration

- A new **Entourage** section in the Open Model N-panel: species dropdown,
  `Add one` / `Scatter along selection` / `Reroll`, density + age + season sliders.
- **Respects the active render mode:** realistic → wire into
  [material_library.py](../blender/pipeline/material_library.py); any NPR mode →
  auto-apply Line Art so trees appear as pen / sketch / linework.
- **Scatter targets come from the contract:** a Revit path / road curve or the
  ground surface that arrived in the bundle.
- Lives inside the already-loaded model — no new ribbon buttons, no instant-render
  trap. Consistent with the Load → Open → Render workflow.

## Output modes (ties to the SVG feature)

Same content, two branches:

1. **Photoreal** — PBR materials, Cycles / EEVEE.
2. **NPR linework** — the Line Art modifier traces the entourage; exports to
   **SVG** (scalable, drop into Illustrator / InDesign / trace in CAD) or PNG.
   `pen` / `sketch` / `linework` go fully vector; `cel` needs GP fills for the
   colour bands (see the SVG-export note).

## Phased roadmap

- **Phase 0 — MVP (proves the pipe):** port eucalyptus to a Python curve-skeleton
  + leaf cards; `Add tree` + `Reroll`; confirm it renders in viewport + photoreal
  + Line Art. One species, end to end.
- **Phase 1 — scatter:** along-curve / on-surface placement with per-instance
  seeds; wire age / season axes.
- **Phase 2 — library:** 5–6 tree species + low-poly scale people; metaball canopy
  toggle.
- **Phase 3 — vector + performance:** SVG entourage export; real-species preset
  packs; GN-instancing / LOD so a forest does not melt the viewport.

## Open decisions / risks

- **Engine:** hybrid (Python skeleton + GN scatter) vs. full GN. Leaning hybrid
  for the MVP.
- **Scope beyond vegetation:** fully procedural for plants; treat people /
  vehicles / furniture as **curated low-poly assets with a few knobs** — procedural
  people is a rabbit hole for little gain.
- **Foliage default:** leaf cards (fast, NPR-friendly) shipped as default, blob as
  a toggle — same as `v8_11`.
- **Performance:** a forest of full-res trees is millions of polys. Strategy: one
  hero mesh per species-variant, GN-instanced with per-instance transform + seed,
  plus proxy LODs.
- **Inspector plumbing:** reading a GN modifier's / shader group's exposed inputs
  and re-presenting them as Blendit's own clean sliders (vs. just showing Blender's
  raw modifier panel). The former is friendlier but more code.
