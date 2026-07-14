# Beyond Revit — the multi-host platform strategy (design doc, parked)

> **Status: strategy adopted, build not scheduled.** The question: can Blendit
> de-integrate from Revit and plug into Rhino, ArchiCAD, SketchUp — becoming a
> general "make architecture models beautiful in Blender" layer rather than a
> Revit add-in? Short answer: **the architecture already supports it**; this doc
> is the considered plan for when (and whether) to act on that.

## The one-sentence reframe

Blendit today is marketed as "Revit → Blender". What the codebase actually
implements is **a host-neutral render product (the contract + the Blender
pipeline) with one host adapter (Revit)**. De-integration is not a rewrite —
it is naming what already exists and adding a second adapter.

## Evidence the seam is real (audited 2026-07-13)

- **`blender/` imports nothing Revit-side.** A sweep for `bir_extract` /
  `bir_ui` / `bir_export` / `bir_bootstrap` / `bir_config` / `Autodesk` across
  `blender/` finds only two *docstring mentions*. Every cross-boundary import
  is `bir_contract` — the seam holds in code, not just in intent.
- **The contract is already host-parameterized.** `Source.app` is a field
  (`"Revit"` is just a default), `Units` carries `source_unit` +
  `scale_to_meters` + `up_axis`, materials are neutral PBR
  (base_color/metallic/roughness/transparency/ior + optional maps), `Element`
  is generic (node/element_id/category/family/level). Nothing in the schema
  *requires* Revit.
- **A non-Revit host already exists and is tested on every commit:**
  `tests/fixtures/build_fixture.py` builds a complete bundle with
  `app="Fixture"` and NO Revit, and the entire pipeline — all 16 looks, camera,
  sun, lights, vector export — runs headless from it. The fixture *is* the
  reference host adapter.
- **Live sync is host-neutral too.** The patch spool is plain JSON
  (`{seq, updated:[meshdata], removed:[nodes], camera?}`) — any host that can
  write a file can drive the live session. Only the *detection* side
  (DocumentChanged/Idling) is Revit-specific, by design.

## The product, renamed

| Layer | What it is | Host-specific? |
|---|---|---|
| **Blendit Core** | `bir_contract` (the bundle format + patch protocol) + `blender/` (16 looks, Live View, 2D drawings, vector export, lights, live-sync applier) | **No** |
| **Host adapter** | Extraction (geometry/materials/camera/sun/lights) + a native UI + launch plumbing | Yes — all of it |
| Today's Revit adapter | `lib/` + `Blendit.tab/` (pyRevit) | The existing product |

**The interop surface is the FILE FORMAT, not the Python library.** A host
does not need to import `bir_contract` — it needs to write a directory with a
conformant `scene_spec.json` + `scene.glb`. That means Ruby (SketchUp), C++
(ArchiCAD), C# (Rhino/Grasshopper components) hosts are all viable without
touching our code. The IronPython-2.7-safe constraint on `bir_contract` exists
for Revit's sake only; it is a convenience library, not the contract itself.

## Conformance levels (what a new adapter must produce)

1. **Minimum viable bundle** — geometry (glb + elements list), units, one
   camera. Everything else has working defaults (default grey materials,
   geographic sun fallback, Nishita sky). *This is a weekend of work per host
   and already yields all 16 looks.* The fixture proves this level.
2. **Full fidelity** — real materials (+texture maps), named views, sun from
   the host's own sun settings, artificial lights, 2D drawing extraction.
   *This is where the months live* (Revit's WYSIWYG extraction — links,
   visibility, RPC, appearance assets — took the bulk of the project). Fidelity
   is per-host grind; the contract caps how weird it can get.
3. **Live-capable** — stable per-element ids + change events feeding the patch
   spool. Requires level 1 only (patches carry raw meshes).

Document this as `docs/contract.md`'s job; add a conformance section there
when the second adapter starts.

## Revit-isms to neutralize (small, do lazily as touched)

- Default strings: `Camera.name="RevitView"`, docs that say "Revit element".
  Cosmetic; fix opportunistically.
- `Element.category` values are Revit category names ("Walls", "Roofs") — fine;
  treat as free text, but the white/clay mode's category-aware future features
  should match loosely.
- `mat_l<instance>_<id>` link namespacing — already just an opaque-string
  convention; other hosts simply won't produce it.
- The `bir_` prefix ("Blender-inside-Revit") across module names. Rename ONLY
  at the moment core is split out (churn otherwise). `bir_contract` →
  `blendit_contract` is the natural landing.

## Host assessments (honest, effort-ranked)

- **Rhino 8 — the right second host.** Embedded CPython 3 (can nearly reuse
  `bir_contract` as-is), `RhinoCommon` meshing (`Mesh.CreateFromBrep`), render
  materials, named views, a sun object, and document events for live sync.
  Massive arch-viz user overlap; Grasshopper opens generative workflows feeding
  Blendit. **Level-1 adapter is days, not months.** This is the proof that the
  abstraction is real: *one host is an implementation, two hosts are a
  platform.*
- **IFC converter — the breadth play.** A standalone `ifc → bundle` CLI
  (IfcOpenShell, pure CPython, no host plugin at all) covers ArchiCAD,
  Vectorworks, Tekla, and any BIM tool's export in one stroke — at the cost of
  WYSIWYG (no live view/camera/visibility). Honest caveat: Bonsai (BlenderBIM)
  already puts IFC in Blender natively; Blendit's differentiation is the
  one-click 16-look pipeline, not the import. Worth doing *after* Rhino proves
  the adapter story.
- **SketchUp — big audience, medium effort.** Ruby API, easy geometry, simple
  materials. Needs a Ruby bundle writer (JSON trivial; use SketchUp's exporters
  or a minimal glb writer). No IronPython-style constraints.
- **ArchiCAD — hardest, defer.** The Python API is query-oriented (no real
  tessellation access); proper extraction means a C++ Add-On. Serve ArchiCAD
  users via the IFC converter first; build native only on demonstrated demand.
- **FreeCAD — trivial but niche.** Python-native, easy adapter, OSS-aligned
  contributor magnet; small arch-viz user base.

## Repo & packaging strategy

**Stay monorepo until the Rhino adapter is real.** Constraints and reasoning:

- pyRevit requires the `.tab` at repo root — the current shape *is* the Revit
  distribution, and the catalog PR depends on it. Don't disturb it.
- A premature `blendit-core` repo means every contract tweak becomes a
  two-repo dance with zero users benefiting. The N=2 rule: split only when the
  second consumer exists.
- When Rhino lands: either (a) `blendit-core` package consumed by both
  adapters (releases/submodule), or (b) keep this repo canonical and have the
  Rhino plugin vendor the `blender/` + `bir_contract/` trees at release time.
  Decide then, biased toward (a) if the Rhino adapter attracts contributors.

## What stays hard (so the strategy stays honest)

- **Fidelity is the moat and the cost.** The contract makes level 1 cheap;
  level 2 (real materials, WYSIWYG views, lights) is a per-host engineering
  grind that no abstraction removes. Budget accordingly; ship level 1 early.
- **Live sync detection is per-host.** The spool + applier are done; each host
  needs its own DocumentChanged-equivalent and the same zombie-handler-class
  discipline lessons (see bir_sync's generation stamping).
- **UI is per-host.** The ribbon, toasts, progress reporting — all re-done per
  host in its native idiom. Thin by design; keep it thin.

## Phased roadmap (each independently shippable)

- **P0 (opportunistic, zero-cost):** keep the seam clean (the audit above is
  the test); neutralize Revit-isms as files get touched; add a contract
  conformance section to docs/contract.md.
- **P1 (the proof):** Rhino 8 level-1 adapter — geometry + camera + basic
  materials → bundle → the full 16-look pipeline just works. Target: a Rhino
  user renders a crosshatch in one click.
- **P2 (the split):** extract `blendit-core`, rename `bir_` → `blendit_`,
  publish the contract spec as the documented interop surface.
- **P3 (breadth):** Rhino live sync (document events → patch spool); IFC
  converter CLI; SketchUp per demand.

## Non-goals

- Replacing host-native renderers or Enscape/Twinmotion feature-for-feature.
- Supporting hosts nobody asks for. Rhino first because the overlap is proven;
  everything else earns its adapter with demand.
- A plugin marketplace / server component. Blendit stays a local, file-based,
  open tool — that simplicity is why adapters are cheap.
