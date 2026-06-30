# Live sync — build-ready plan (code-grounded)

> Companion to [live-sync.md](live-sync.md) (the vision). This is the **plan you
> build from**: every assumption pressure-tested against the actual code, the open
> questions decided with evidence, the unknowns reduced to small spikes you run
> *before* committing to the build. Goal: when the build starts, it runs flawlessly
> because the hard parts are already proven.

## 1. Code audit — what's verified, what the vision doc got slightly wrong

| Claim (live-sync.md) | Reality in the code | Consequence |
|---|---|---|
| Extraction is per-element | ✓ `extract_geometry` loops elements, tessellates each ([geometry.py:38](../lib/extract/geometry.py)) | Refactor: factor the loop **body** into `extract_element(doc, elem, opt)`; the full extract and a delta both call it. |
| Node id is the join | ✓ but **element ≠ node** | A multi-material element emits **N** nodes `<cat>_<id>_<n>` ([geometry.py:64-72](../lib/extract/geometry.py)). The delta **unit is the element** (its whole node-set); a material edit changes the node *count*. |
| Blender finds objects by node id | ✓ **reliable** (spike-confirmed) | Imported object names == spec element nodes **exactly** (`Box_1`, `Glass_1`); node names are unique by construction (category-no-spaces + numeric id [+ `_n`]). Belt-and-suspenders: stamp `obj["node"]` at import. |
| Apply-loop + transport reusable | ✓ transport; ⚠️ **apply must NOT reuse the glTF importer** | [merge.py](../blender/pipeline/merge.py) proves `bpy.ops.object.join` **silently fails in the session's timer context** (the "white mode" bug) — which is why merge uses bmesh. The glTF importer uses `bpy.ops.import_scene.gltf`; **do not assume it's timer-safe.** |
| Persistent session on timers | ✓ `bpy.app.timers.register(_deferred_setup, ...)` ([live.py](../blender/interactive/live.py)) | The watcher is one more timer, same pattern. |
| Spool dir IPC | ✓ natural rendezvous | Open Model launches Blender **detached** (`subprocess.Popen`) with `--bundle <dir>` ([OpenModel](../Blendit.tab/Render.panel/OpenModel.pushbutton/script.py)). Both sides already share that dir → spool patches in `<bundle>/patches/`. No sockets. |

**Spike-proven today (headless):** un-merged `import_bundle` gives one object per element with a clean node→object map; **mesh replace-in-place (`obj.data = m`), object remove, and `from_pydata` add all work via pure data API** — the same class as the bmesh merge that already runs safely in the session context.

## 2. Decisions (the open questions in live-sync.md, now closed)

1. **Apply = raw-mesh data API, not glTF-in-timer.** A patch carries raw `MeshData`
   (verts/faces/material_id) as JSON; the apply loop builds meshes with
   `mesh.from_pydata(...)` and swaps `obj.data`. *Evidence:* the merge `bpy.ops`
   trap + today's spike. **Bonus:** `from_pydata` uses Revit Z-up feet directly — no
   glTF Y-up round-trip — so deltas are simpler than the full import.
2. **Live session runs un-merged.** Per-element identity is what deltas need;
   merging collapses it. Lit modes (Realistic/White/Shadow/Specular) render fine
   un-merged. **Line Art stays a freeze + Regenerate step**, not live (it's the only
   object-count-bound path). *(live-sync.md option 1 — cleanest v1.)*
3. **Join robustness:** rely on node names (reliable) **and** stamp `obj["node"]` id
   property at import; rebuild `node_to_object` from it on `.blend` reopen.
4. **Delta granularity = element.** Dirty element id → look up its node-set in the
   `elements` index → re-extract → replace that node-set. Diff old vs new nodes to
   add/remove sub-nodes (material change). A "modified" element that became
   **hidden/filtered** in the view emits a **removal** (re-check view visibility on
   extract — a gap the vision doc skips).
5. **IPC = shared-bundle-dir spool + file polling.** `<bundle>/patches/patch_<seq>.json`.
   Back-channel (Phase C) = reverse spool `<bundle>/back/`. Sockets deferred — never
   needed for A/B, optional for C.
6. **Subscription lifecycle:** idempotent register (single-source flag), heartbeat
   singleton, defensive re-subscribe — survives rocket-mode engine recycles.
7. **Scale + axis (precise):** delta meshes are Revit feet, Z-up. **Replacing** an
   existing object's mesh keeps the object's existing `scale` transform → auto-scaled
   correctly. **Added** objects must get `scale = scale_to_meters` set (as
   [import_bundle._apply_scale](../blender/pipeline/import_bundle.py) does for roots).
   No axis swap (both Z-up; glTF Y-up was only the full-transport's intermediate).
8. **Contract stays at 0.1.0.** A patch is a transport-level envelope, not a
   SceneSpec concept: `{seq, updated:[meshdata], removed:[node], camera?}`.

## 3. Spikes — run these BEFORE building (each tiny, each kills one unknown)

- **R1 (Revit) — THE gate, still open.** A standalone "Live Sync on" button:
  subscribe to `Application.DocumentChanged` (idempotently), record
  `GetAddedElementIds/GetModifiedElementIds/GetDeletedElementIds` into a set; on
  `Application.Idling` print the counts and clear; "Sync Off" unsubscribes. **No
  Blender, no extraction, no transport.** Prove: no duplicate handlers on re-click,
  survives a few edits + an engine recycle, zero leak when off. *If this holds, the
  rest is plumbing we already have parts for.*
- **B1 (Blender) — DONE ✓** (today): un-merged import join + data-API
  replace/remove/add.
- **B2 (Blender, GUI):** in a running Open Model session, register a
  `bpy.app.timers` poll that applies a **hand-made** patch dropped in the spool;
  confirm it lands live and measure latency. *(Needs the GUI event loop — can't be
  headless; timers don't fire under `--background`.)*
- **E1 (end-to-end thin slice):** Idling writes a real patch for **one moved
  element** → session applies → it moves. The smallest complete loop; everything
  after is breadth.

## 4. Phase A — file-by-file (Revit→Blender geometry deltas + Sync UI)

**Revit (IronPython 2.7, pure-ASCII chain):**
- `lib/extract/geometry.py` — factor out `extract_element(doc, elem, opt)`; `extract_geometry` calls it in its loop (no behaviour change; unit-testable shape).
- `lib/extract/delta.py` *(new)* — `build_patch(doc, view3d, dirty_ids) -> (meshdata_list, removed_nodes)`: builds `opt`, re-checks visibility, maps each dirty element id → its nodes, re-extracts present ones, lists removed.
- `lib/sync.py` *(new)* — the engine: `DocumentChanged` handler (accumulate dirty ids, no heavy work), `Idling` handler (flush → `build_patch` → `transport.write_patch`), idempotent `subscribe()/unsubscribe()`, `Live/Trigger/Off` state + heartbeat singleton.
- `contract/transport.py` — `write_patch(spool, seq, meshes, removed, camera=None)` / `read_patch(path)` / `patch_dir_of(bundle_ref)` (IPy-safe; raw-mesh JSON).
- `Blendit.tab/Render.panel/Sync.pulldown` *(new)* — **Live Sync / Trigger Sync / Sync Off** (+ **Sync Now** for Trigger). Off is default.

**Blender (CPython):**
- `blender/interactive/sync_apply.py` *(new)* — the timer callback: poll `patches/`, read in `seq` order, apply by node via data API (build `from_pydata`, swap/replace, remove, **assign material by id**, set scale on adds), delete the patch, repeat. Returns the poll interval.
- `blender/interactive/live.py` — add `--watch <spool>`; when set: **skip merge** (un-merged), stamp `obj["node"]`, `bpy.app.timers.register(sync_apply.poll)`. Clear stale patches on startup.
- `blender/pipeline/materials.py` (or import path) — `assign_material_by_id(obj, mat_id, spec)` reused by delta adds (the preset library already builds materials by id).

**Tests:**
- `tests/test_patch_roundtrip.py` (CPython) — `write_patch`/`read_patch` envelope.
- `tests/headless_sync_apply.py` (Blender) — un-merged import, then apply a synthetic patch (update + add + remove) through the **real** apply function; assert object/mesh state and material assignment.

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Revit subscription under rocket mode (duplicate handlers / dropped sub) | **Spike R1 first**; idempotent flag + heartbeat + defensive re-subscribe. |
| `bpy.ops` unreliable in timer | Avoided entirely — data-API `from_pydata` (evidence: merge + B1). |
| Hide/show isn't a geometry edit but changes the view | Delta re-checks view visibility; emits removal when no longer visible. |
| Material edit changes an element's node count | Replace the whole node-set; diff old/new nodes to add/remove sub-nodes. |
| New material id appears in a delta | Patch carries the material id; if unknown, fall back to default + flag a full refresh (rare). |
| Patches pile up if Blender is closed | `seq`+timestamp; session clears stale on startup; Revit caps spool depth. |
| Scale/axis drift on delta meshes | Replace reuses object scale; adds set `scale_to_meters`; no axis swap (Z-up both). |

## 6. Phasing (each independently shippable)

- **A — geometry deltas + Sync pulldown** (this plan). The headline.
- **B — camera sync:** push the active view camera on the same spool; flying in Revit moves the Blender shot.
- **C — entourage round-trip:** reverse spool `<bundle>/back/`; Blender writes a tree's *recipe* (species/seed/transform), Revit drops a lightweight placeholder on a Blendit workset via `ExternalEvent` + `Transaction`. Bidirectional; the novel piece. (Dovetails with [entourage.md](entourage.md).)

## 7. First commit, when we build

Order that keeps every step green: **R1 spike → `extract_element` refactor (no behaviour change, full regression stays green) → patch transport + roundtrip test → `sync_apply` + headless test → `--watch` un-merged session → Sync pulldown → E1 end-to-end.** Nothing lands until its test is green; the contract never moves.
