# Hatch — Tonal Art Maps (design note)

> **Status: Phases 1–2 BUILT (the `hatch` mode); Phase 3 SHIPPED as the separate
> `crosshatch` mode.** The Hatch render mode uses surface-attached,
> perspective-correct procedural hatch lines with a nested cross-hatch
> (Phases 1–2). The authored-TAM renderer this note designed as "Phase 3" was
> built out-of-repo (the `realtime-hatching` project), validated there, and
> integrated as **Crosshatch** — see the section at the end. The two modes
> coexist: `hatch` draws the shadows (Shader-to-RGB tone incl. cast shadows),
> `crosshatch` draws hand-authored strokes from analytic sun tone.

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

## Crosshatch — the authored-TAM realization (SHIPPED)

Phase 3's TAM half landed as the sixteenth mode, `crosshatch`, from the
out-of-repo `realtime-hatching` project (a faithful Praun implementation,
validated on spheres/cylinders/organics before integration):

- **The TAMs are real** (point 2 above, done properly): `tools/tam_generator.py`
  implements the paper's Section-4 automatic construction — 4 mip levels ×
  6 tone columns, toroidal, stroke-nested both ways, constant *pixel* width
  per level — in four styles (**ink, brush, sketchy, charcoal**), shipped as
  96 small PNGs under `blender/resources/hatch_tam/tam_<style>/`.
- **Rendering is a Cycles OSL shader** (`tam_hatch.osl`), not hardware mips:
  `filterwidth()` picks the mip whose texel matches the screen pixel, so
  strokes keep constant SCREEN width and tone changes by add/remove — the
  paper's actual trick, beyond what EEVEE nodes can express. Cycles-only,
  CPU; the emission-only shading converges in very few samples. Tone is
  analytic Lambert from a light-direction *input* (no Shader-to-RGB in
  Cycles) — so no cast shadows by design; an AO/shadow bake multiplied into
  tone is the noted v2 hook. **The default tone light is a camera-relative
  artist's key** (`hatch_tam.aim_camera_key()`: 45° over the left shoulder,
  38° altitude, re-derived per render) because tone is the entire image and
  a site-accurate sun can backlight a shot into uniform flat hatch — the
  sample residence's 21:00 spec sun did exactly that. Live View's "Follow
  Scene Sun" toggle switches to `sync_sun()` (tracks the lamp; reads
  `rotation_euler`, NOT `matrix_world`, which is stale in the pipeline path).
- **The parameterization is the pragmatic half** (point 1 stayed parked):
  instead of a curvature field, `hatch_tam.ensure_tam_uv()` bakes a
  dominant-axis box projection per face ("TamUV", world metres) — the
  triplanar idea as REAL UVs with hard seams at corners. Right for coarse
  planar Revit geometry; the lapped/curvature variant for organics exists in
  the source project (`tam_hatch_lapped.osl` + `lapped_field.py`) and on the
  `hatch-flow-experiment` branch, still out of scope.

Integration facts future-you will want (all encoded in `blender/pipeline/
hatch_tam.py` docstrings): Script-node sockets are created by a GUI-only
operator, so the compiled material ships in `tam_hatch_template.blend`
(rebuild via `tools/build_crosshatch_template.py`, GUI required, whenever the
shader's parameter list changes); UVs MUST enter via the template's UV Map
node — the `getattribute(uv_name)` path silently reads zeros headless (Cycles
never exports a UV layer no node requests); engine flags (shading_system, CPU
device, denoise OFF — denoising smears strokes) are derived from the mode in
`engine.py setup_engine` via `registry.OSL_MODES`, never written into the
shared spec, so they self-heal on every mode switch.

Tuning that MATTERS (each was a visible failure before it was fixed):
- **uv_scale 0.5 tiles/metre.** The custom-mip system works while one tile
  spans ~32–256 SCREEN px; at whole-building framing (~35 px/m) that means
  metres-wide tiles. 3.0 put tiles at ~12 px → sub-pixel strokes aliasing
  into flat grey "dense noise".
- **ambient 0.15.** Full shadow → darkness 0.85 → the dense cross-hatch
  columns (~5). 0.5 (mis-ported from the procedural hatch's tuning, where
  tone drives line width, not stroke count) capped darkness at 0.5, so no
  surface could ever draw past the mid sparse-dash column.
- **20° sun-altitude floor** on the shader input only (used when following
  the scene sun; the artist's key sits at 38° by construction).
