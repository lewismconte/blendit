# Live sync — delta link to a persistent Blender (design doc, parked)

> **Status: draft / parked.** Vision + architecture, not committed work. Nothing
> here is built yet. This is the Phase-4 "true live link" the bridge was designed
> for (CLAUDE.md §11). Develop or trim later. Sibling of [entourage.md](entourage.md)
> — that doc is the *content*, this is how content + edits *stream* live.
>
> **→ For the build-ready, code-grounded plan (assumptions verified, decisions
> closed, spikes to run first), see [live-sync-plan.md](live-sync-plan.md).**

## The idea

Today's flow re-extracts the whole active view on **Load Model**. A live link
instead streams **only what changed**: edit in Revit, see it reflected in the
running Blender session in ~1–2s, having re-tessellated just the handful of
elements you touched. Same idea as Enscape / Twinmotion Direct Link — and honestly
those are sluggish even on fast machines, so near-parity is a fine bar.

The efficiency win is the whole point: a 5,000-element model never re-exports to
move one wall; you ship a patch of one node. And entourage placed in Blender can
round-trip back to Revit as a *lightweight placeholder* (params, not mesh), so the
.rvt stays light while Blender holds the heavy procedural geometry.

## What's already in place (why this is tractable)

The bridge was built for this; three load-bearing pieces already exist:

- **Extraction is already per-element.** [geometry.py](../lib/extract/geometry.py)
  loops elements and tessellates each independently. Delta extraction = run that
  loop on a *dirty id set* instead of the whole view.
- **Stable node keys are the join.** Every mesh is named
  `<category>_<elementId>` ([geometry.py:67](../lib/extract/geometry.py)) —
  deterministic from the Revit element id. That's the handle Blender uses to find
  and replace exactly the objects that changed.
- **The apply-loop + transport already exist.** [live.py](../blender/interactive/live.py)
  already runs a persistent session on `bpy.app.timers`; the glTF transport +
  importer are reusable for a "patch" bundle. A delta is just a tiny bundle.

## The loop

```
REVIT (IronPython)                         BLENDER (persistent bpy)
  edit (transaction)                         live EEVEE view
        |                                          ^
  DocumentChanged  -> dirty ids                Apply by node id
        |                                          ^
  Idling: extract changed  --- DELTA PATCH --> Watcher / timer
        ^                                          |
        +------- entourage params (not mesh) <-----+
```

**1. Detect (Revit).** Subscribe to `Application.DocumentChanged`; it hands you
`GetAddedElementIds()` / `GetModifiedElementIds()` / `GetDeletedElementIds()` after
every transaction. Do **no** heavy work there — just record the dirty ids into a
set.

**2. Extract (Revit, on Idling).** `Application.Idling` fires when Revit is idle and
gives a valid API read context. Batch-extract the dirty set there. Refactor:
factor the per-element body of `extract_geometry` into `extract_element(doc, elem,
opt)`, callable on the whole view (Load Model, today) **or** a dirty id list (patch).

**3. Transport.** A delta is a small `.glb` with only the changed nodes + a
`removed: [node ids]` list + (optionally) the camera. **v1 = a spool directory**:
Revit writes `patch_NNNN.glb`/`.json` to a watched folder; Blender's timer polls,
applies, deletes. No networking, reuses the whole transport + importer. A localhost
socket / WebSocket is the eventual upgrade (lower latency, and *required* for the
back-channel) but it's strictly more moving parts.

**4. Apply (Blender).** A timer reads the patch and, by node id: imports new nodes,
replaces changed objects' meshes in place, deletes removed ones. **Use the data API
/ bmesh, never `bpy.ops` in the timer context** — that's the recurring live-session
trap (the white-mode merge bug); the codebase already knows to avoid it.

## Revit UX — three sync modes

A **Sync** control on the Render ribbon with three explicit states (a pulldown or
three buttons, clearly labelled so the user always knows what's listening):

| Mode | Behaviour |
|---|---|
| **Live Sync** | Subscribe to `DocumentChanged`; auto-flush accumulated deltas on `Idling`. The continuous Enscape-style link. |
| **Trigger Sync** | Keep accumulating the dirty set, but only push on button press. Controlled / low-distraction — do a big edit, then sync once. Cheap (still only the changed nodes since the last trigger). |
| **Sync Off** | Unsubscribe entirely. No listening, no pushing — zero overhead, no surprises. The **default** and the safe state; reverts to today's Load / Open / Render. |

> Live and Trigger both keep the `DocumentChanged` accumulator running; Live
> auto-flushes on Idling, Trigger flushes on click. Off stops accumulating and
> drops the subscription. The mode *is* the subscription lifecycle.

The existing Load / Open / Render buttons stay — live sync is an additive mode, not
a replacement. Open Model launches/attaches the persistent Blender session that
Live/Trigger feed.

## The hard decisions

1. **Merge-vs-identity — the central tension.** `merge_by_material`
   ([merge.py](../blender/pipeline/merge.py)) collapses per-element objects into
   one-per-material because Line Art + rendering are object-count-bound (5–14×
   faster) — but that destroys the per-element identity deltas need. Options, in the
   order I'd lean:
   - **Run live-sync un-merged in lit modes.** Per-element objects render fine in
     Realistic / White / Shadow; only Line Art is object-count-bound. So the live
     link runs un-merged (cheap deltas) and Line Art stays a freeze + Regenerate
     step. Cleanest v1.
   - **Incremental re-merge:** keep an element→material-group index and rebuild only
     the affected group(s) per delta. Preserves fast Line Art; needs the source
     meshes kept. More plumbing.
   - Hybrid: merged static background + un-merged active working set. Most complex.

2. **Revit threading.** You cannot call the Revit API freely off the main thread.
   All reads happen on `Idling`; anything that *writes* back (the entourage
   round-trip) needs an `ExternalEvent` + `Transaction`. This discipline is what
   keeps it from crashing Revit, and it caps latency at Idling cadence (fine for
   near-live).

3. **Session lifetime + rocket-mode safety.** A persistent Blender process + a live
   Revit event subscription must survive the whole session. Rocket mode (persistent
   engine) actually *helps* — a once-registered listener stays alive. The risk is
   **correctness, not speed**: under a reused engine, naive registration stacks a
   second `DocumentChanged` handler on the next "Live Sync on" click (double
   extraction), and an engine recycle can silently drop the subscription. So:
   idempotent registration (a single-source flag), a heartbeat singleton, and
   defensive re-subscribe — the same pattern Sync Sprint already uses. (Rocket
   mode's only perf cost is ~0.5–2s of cold-start *launch latency* per click when an
   extension is incompatible — irrelevant next to extraction/render time, but we
   stay compatible regardless.)

## Entourage round-trip — recipe in Revit, geometry in Blender

When you place a tree in the Blender session, the back-channel sends **just its
recipe** — species, seed, transform — to Revit, where (on an `ExternalEvent` +
`Transaction`) it drops a **lightweight placeholder** (a generic / adaptive point
family carrying those params) onto a dedicated **Blendit workset**:

- **Revit stays light** — a point + a few params, *not* a 50k-poly mesh. The heavy
  procedural geometry lives only in Blender, regenerated from the recipe. This is
  "recipe in Revit, geometry in Blender," and it dovetails exactly with the
  parametric-entourage design (params + seed *are* the asset — see
  [entourage.md](entourage.md)).
- **The workset is the off-switch** — toggle the whole entourage layer off so it
  never bloats deliverable views / sheets, and it round-trips in true project
  coordinates so it survives.
- **Caveat:** worksets only exist in *workshared* models. For a single-user file,
  fall back to a Design Option or a tagged subcategory — same idea, different
  container. This gates the literal "workset" wording, not the concept.

This is the bidirectional, hardest, most novel piece — and the one that most
distinguishes Blendit from a one-way viewer.

## Honest ceiling

Not Enscape's 60fps GPU stream — that's a native C++ addin with deep API hooks.
Through a pyRevit / IronPython bridge you get a **near-live link**: edit → reflected
in ~1–2s, syncing only deltas. Given Enscape's own link is sluggish, that's a fine
bar — and it's a massive efficiency win over re-extracting the whole model. The
bridge constraint (no `bpy` in Revit) is permanent, but it's *why* the delta shape
is right, not a limitation.

## Contract impact

A patch is a **transport-level** addition, not a new contract concept: it reuses the
existing glTF nodes + the `<category>_<elementId>` naming. Likely additive — a small
"patch" envelope (`{added/updated: glb, removed: [node ids], camera?}`) alongside
the full bundle. Aim to keep the SceneSpec contract at its current version; the
delta lives in the transport layer the seam was designed to swap.

## Phased roadmap

- **Phase A — Revit→Blender geometry deltas (the live view):** DocumentChanged +
  Idling, `extract_element` refactor, spool-dir patches, timer apply by node id,
  un-merged lit modes, the Sync pulldown (Live / Trigger / Off). Headline feature on
  its own.
- **Phase B — camera sync:** push the active view's camera on the same channel so
  flying in Revit moves the Blender shot.
- **Phase C — Blender→Revit entourage round-trip:** the socket back-channel +
  ExternalEvent / Transaction placeholder-on-workset. Bidirectional.

Each phase is independently shippable.

## Cheapest first step (de-risk before building)

The single biggest unknown is whether pyRevit can hold a `DocumentChanged` /
`Idling` subscription cleanly under rocket mode across a session. De-risk it with a
tiny standalone spike that just **logs dirty element ids on each edit** — no Blender,
no extraction, no transport. A "Live Sync on" button subscribes (idempotently) and
prints `added/modified/deleted` counts to the pyRevit output on every transaction;
"Sync Off" unsubscribes. If that holds (no duplicate handlers, survives a few edits
+ an engine recycle), the foundation is proven and the rest is plumbing we already
have the parts for.
