# Hatch — Tonal Art Maps (design note)

> **Status: Phases 1–2 BUILT; Phase 3 parked research.** The Hatch render mode now
> uses surface-attached, perspective-correct hatch lines with a nested cross-hatch
> (Phases 1–2). This note records the source method and the path to the
> research-grade Phase 3 for later style work.

## Source

Praun, Hoppe, Webb, Finkelstein — **"Real-Time Hatching"**, SIGGRAPH 2001
(`ASSETS/01_Revit/Danpal - Complete Library/hatching.pdf`). Two ideas:

- **Tonal Art Maps (TAMs):** a 2-D array of pre-drawn stroke images — columns =
  tone (light → dark), rows = mip resolution. The **nesting rule**: every stroke in
  a lighter/coarser image also appears in all darker/finer ones. That guarantees
  *tone coherence* (strokes are added as a surface darkens, never swapped) and
  *screen-space density coherence* (strokes drop out as the surface recedes, so
  hatch spacing stays constant on screen — no clumping far / thinning near).
- **Surface attachment:** the (tileable) TAM is pasted over the mesh as overlapping
  **lapped-texture** patches that follow a tangential **direction field** (from
  curvature). Strokes then *follow the form* and are perspective-correct because
  they live on the surface. Swapping the stroke texture = a different **style**.

## What we built (Phases 1–2)

Blendit's hatch is a procedural EEVEE shader (`npr.make_hatch_material`), not a
textured TAM renderer. It captures the *spirit* of the paper without authored
textures, UVs, or a direction field (Revit gives us no UVs):

- **Phase 1 — surface-attached strokes (triplanar).** The stripe pattern is built
  from **world Position + Normal** (triplanar: three world-axis projections blended
  by `|normal|^4`), not the view ray. So strokes lie in each surface's own plane —
  vertical walls get verticals, floors / roofs / ground get in-plane strokes,
  rotated faces follow their own walls — and everything stays perspective-correct.
- **Phase 2 — nested, surface-aligned cross-hatch.** A perpendicular pass (the
  in-plane cross direction) that only switches on below a `cross_dark` tone, so
  cross-hatch appears *only in the shadows* — the nesting idea, done procedurally.
  Tone still drives line **width** (continuous lines, stepped bands); `weight`
  scales it; `density` is lines per metre on the surface.

This fixed the two real problems with the old view-ray hatch: cross-hatch was
concentric rings around the camera (now a surface-aligned grid), and only vertical
surfaces read correctly (now all orientations do).

**Known limit:** triplanar approximates surface attachment by *world axis*, not a
true tangential direction field — so on smooth organic forms (a sphere) the three
projections show blend seams and the hatch doesn't *flow* around curvature. For
architecture (axis-aligned + rotated planar faces) this is a non-issue; the
direction field is what Phase 3 adds.

## Phase 3 — true TAMs + direction field (parked, research-grade)

To match the paper on curved geometry and to unlock swappable hand-drawn **styles**:

1. **A tangential direction field** over the mesh (curvature-based à la
   Hertzmann–Zorin, or user-painted). Blender has no native one — likely a
   Geometry-Nodes or Python preprocess that bakes a per-face/vertex direction
   (+ a UV/lapped parameterization) into attributes. This is the hard part, made
   harder because **Revit geometry arrives with no UVs** (the contract emits
   positions only).
2. **Nested stroke textures (the TAM).** A stack of hand-drawn or generated stroke
   images obeying the nesting rule (tone columns × mip rows). Blend the two
   bracketing tone images by the shaded value; let hardware mip-mapping cover
   resolution (an approximation of the paper's hand-crafted mip nesting). Threshold
   for crisp ink vs. leave grey for pencil/charcoal.
3. **Style = the TAM.** Different stroke textures → pencil, technical ink, charcoal,
   engraving — swappable, exactly the "tinker for styles" goal.

Effort: substantial (a parameterization/direction-field pipeline + a TAM authoring
or generation step). Worth doing only when curved-surface hatching or multiple
hand-drawn styles become a priority. The procedural Phases 1–2 cover architectural
hatching well in the meantime, and a middle step — replacing the procedural stripe
with a **procedural multi-layer "mini-TAM"** (several nested density layers added by
tone) — could improve tonal smoothness before committing to textured TAMs.
