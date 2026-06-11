# UT2004 DM Map Project — Progress & Roadmap

A living "save state" for the project. Read this together with [CLAUDE.md](CLAUDE.md),
which holds the durable context (goal, file-format essentials, architecture decision).
This document tracks **where we are and what's next**.

Last updated: 2026-06-10

---

## Step 7 — Full-map replication (IN PROGRESS, blocked on final save)

**Goal:** replicate `DM-Rankin.ut2` end-to-end through our pipeline.

**Done:**
- Whole-map T3D now follows the Level object's actor list (CSG-critical brush order),
  decodes non-native structs (Scale/PointRegion/emitter ranges) as nested tagged streams,
  emits sub-objects (`Begin Object` for `export` arrays like Emitters/Actions), and matches
  the engine's own `myLevel.T3D` export at **99.95% byte-identical** (27 differing lines of
  62,685, all class-default verbosity). All 39 maps emit clean balanced T3D.
- **Imported our generated T3D into UnrealEd → Build Geometry → the ENTIRE map reconstructs**:
  BSP rebuilt from our decoded brushes, textures applied, actors placed. Visually confirmed in
  the editor (textured 3D view of the real Rankin interior). This proves the decode→T3D→engine
  reconstruction works for full level geometry, not just actor placement.

**BLOCKER — cannot write the replica `.ut2` to disk.** `MAP SAVE` fails with "Couldn't save
package - maybe file is read-only" (reproduced to two writable folders; not a filesystem perm
issue — verified `C:\UT2004\Maps` is writable). Editor.log root cause: our faithful T3D
references the original map's **private/regenerable objects** by their `DM-Rankin.*` path —
`StaticMeshInstance` (680, regenerated on Build), `ReachSpec` via `PathList`/`UpstreamPaths`
(909, rebuilt by Build Paths), the explicit `Brush=Model'DM-Rankin.ModelN'` names (554),
`Screenshot`/`Summary`/`ZoneEffect`/`AntiPortal`. Because the original `DM-Rankin.ut2` must
stay loaded to supply its *embedded* meshes/textures (shared-asset refs like `StaticMesh`/
`Shader`/`Texture`, which are legitimately fine), these private refs bind cross-package and
UnrealEd refuses to save a map that references another package's private objects.

**Fix — APPROVED by user, NOT yet implemented (immediate next task):** add a
"portable/saveable" T3D mode that omits refs to engine-regenerated/private map-local objects
(`StaticMeshInstance`, `PathList`/`UpstreamPaths`, the `Brush=Model` line,
`Screenshot`/`Summary`/`ZoneEffect`/`AntiPortal`) while keeping legitimate shared-asset imports
(`StaticMesh`/`Shader`/`Texture`). The engine regenerates the omitted objects on Build
Geometry/Lighting/Paths. Trade-off: diverges from byte-identical (intentionally) to produce a
re-importable, saveable map.

  - **User also requested:** emit an **omissions manifest** (JSON + readable log) listing every
    dropped reference — actor, property, omitted object + class, and a **disposition**:
    `auto-regenerated` (StaticMeshInstance→Build Geometry, ReachSpec/PathList→Build Paths,
    Model→CSG) vs `manual/cosmetic` (Screenshot, Summary, ZoneEffect) — so anything needing
    manual re-placement is explicit.
  - **Then:** re-run the UnrealEd round-trip (Import → Build Geometry → Save As) to produce the
    actual `DM-Rankin-Replica.ut2`. NOTE the GUI save path: the long hidden-`.claude` worktree
    path may trip UnrealEd's old file code — save to a short path like `C:\UT2004\Maps\`.
  - **Tooling note for the round-trip:** computer-use clicks worked for menus/dialogs, but
    modal popups occasionally needed a Win32 `BM_CLICK` (via PowerShell) to dismiss; two
    UnrealEd instances can spawn if `open_application` is called twice — kill the extra.

## Step 8 — Map-inventory pattern analysis (DONE ✅)
Goal-part 2: mine the 39 maps for repeatable bot-pathing / inventory patterns.
- **`navanalysis.py`** — decodes the nav graph (NavigationPoint nodes + ReachSpec edges with
  reachFlags semantics) and inventory placement; prints per-map + cross-map reports (`--json`).
- **`NAV_PATTERNS.md`** — findings. Key invariants across all 39 maps: **1.00 InventorySpot per
  pickup**, **out-degree ~4.2**, edge mix **82% walk / 14% jump / 1% forced / 1% special**,
  ~16 PlayerStarts/map. Distilled repeatable sub-structures: pickup anchoring, PathNode mesh,
  jump links, and the parametric **lift template** (Mover + LiftCenter + LiftExit×floors tied
  by LiftTag, bidirectional R_SPECIAL edges). The engine rebuilds ReachSpecs via Build AI Paths
  — which is why omitting them from our T3D (Step 7 fix) is safe.

---

## The goal (recap)

Read, interpret, and ultimately reconstruct **official UT2004 Deathmatch maps**, with the
longer-term aim of programmatically generating/modifying them. Scope is the stock maps that
shipped with the game — not custom community content.

**Architecture (from CLAUDE.md):** *read binary, write via T3D.*
1. **Read** the binary `.ut2` directly in Python.
2. **Write** changes as plain-text **T3D** (UnrealEd's export format).
3. **Finalize** in UnrealEd: Build Geometry → Build Lighting → save `.ut2`.

---

## Component detail — Steps 1–6 (read/decode/T3D foundation)

*(Live status is at the top: Step 7 replication is blocked on the `.ut2` save; Step 8 pattern
analysis is done. The sections below document the foundation those build on.)*

### Step 6 — brush/BSP geometry decoded ✅

The full **read → decode → generate-T3D → engine-import** loop is proven (Step 5), and we now
reconstruct **brush geometry** — the part CLAUDE.md flagged as "hard / not fully public".
Editor-brush polygons decode from the binary `Model → Polys → FPoly` chain and emit as
`Begin Brush … Begin Polygon …` blocks that are **byte-identical to the engine's own T3D
export** (523/523 brush models in DM-Rankin; 81k polygons across all 39 maps). Combined with
schema-driven enums/arrays, overall T3D line coverage vs. the engine reference is **~92%**.

### Done
- **`ut2parser.py`** — dependency-free Python reader for the Unreal package format.
  - `Reader` with Unreal primitives, incl. the two that bite:
    - **signed compact index** (1–5 bytes; byte 0: `0x80`=sign, `0x40`=continuation, low 6 bits value).
    - **length-prefixed FString** (compact-index length, ANSI, NUL-terminated).
  - `parse()` validates magic `0x9E2A83C1`, reads the header, and walks the
    **name / import / export** tables with full name + object-reference resolution.
  - **`read_properties(pkg, export)`** decodes the tagged-property stream of any export:
    skips the `RF_HasStack` FStateFrame prefix, then reads `name → info → [struct] →
    size → [array index] → value`. Interprets Byte/Int/Bool/Float/Object/Name/Str/Class
    and the `Vector`/`Rotator`/`Color`/`Scale` structs; anything else is kept as raw bytes
    with exact realignment so the stream never desyncs.
  - **`actor_model(pkg, path)`** builds a JSON-serializable model — every actor with class,
    name, and decoded properties; repeated array elements collapse into lists.
  - **`to_t3d(pkg)`** generates Map T3D (`Begin Actor … End Actor`) from the decoded
    properties: scalars, strings, names, fully-qualified object refs (`Class'Pkg.Group.Name'`
    via outer-chain walking), and `Vector`/`Rotator`/`Color`/`Scale` structs with
    engine-style default-component omission. Engine-recomputed fields (`Region`,
    `ColLocation`) and not-yet-decoded arrays are skipped.
  - `ObjectRef` value type: prints the plain name in summaries/JSON, the qualified ref in T3D.
  - **Schema-driven refinement** (Step 6): loads `schema.json` and resolves **enum bytes**
    to names (`LightEffect=LE_NonIncidence`, `DetailMode=DM_Low`) and decodes **dynamic
    arrays** to typed elements (`PathList`→`ReachSpec` refs, `Skins`→`Material` refs), emitted
    in T3D as `Prop(i)=value` with null entries omitted. Degrades gracefully if schema absent.
  - **Brush geometry** (Step 6): `model_polys_ref()` walks a Brush/Volume actor's
    `Brush`→`Model` and deterministically parses the UModel header to find its `Polys` object;
    `decode_polys()` reads the native `FPoly` array (NumVerts byte, Base/Normal/TextureU/
    TextureV + vertex vectors, flags, Texture/Item refs, iLink). `to_t3d` emits the
    `Begin Brush / Begin PolyList / Begin Polygon …` block — **byte-identical to the engine**
    (Item/Texture/Flags/Link ordering, `+013.6f` coords, omitted `Link=-1`, `-0.0`→`+0.0`).
  - CLI: `--summary` (default), `--actors`, `--json` (`--all-objects`), `--diff A B`,
    and `--t3d` (`--t3d-class C`, `--t3d-clean`).
- **`schema_extractor.py`** — parses UnrealScript exported by `ucc batchexport <pkg>.u Class
  UC <dir>` into `schema.json` (enum value lists + array inner-types). Built from Core, Engine,
  UnrealGame, XGame, Gameplay, XPickups, XWeapons, XEffects (100 enum props, 192 array props).
- **Verified against all 39 stock DM maps:**
  - Tables: 0 failures, every object reference resolves, one `Level` per map. Versions 18×v127, 21×v126.
  - Properties: every export in every map decoded — **0 errors, 63,981 placed actors** recovered.
  - JSON: all 39 maps emit valid, parseable JSON.
  - T3D: all 39 maps emit well-formed, balanced T3D with no unresolved refs (81,168 polygons
    total). Diffed against the engine reference for DM-Rankin: **~92% of all property+geometry
    lines reproduced verbatim**. Non-brush: `LightEffect` 173/173, `PathList` 891/891, `Skins`
    177/177 exact. Brush: **523/523 editor-brush models byte-identical**. StaticMeshActor 664/664.
    Remaining gap = Emitter structs + built-BSP volume models (below).

### What parses cleanly today
Header, name/import/export tables, the **full object inventory**, the **per-actor property
set** (class, `Location`, `Rotation`, `DrawScale`/`DrawScale3D`, names, refs, scalars, common
structs), and a **JSON actor model** ready for transform/diff. Output reads exactly like a
real DM map (`StaticMesh="houretrim"`, `Light` with `LightBrightness`, `PathNode` nav lists).

### Known limitations / not yet decoded
- **Emitter particle-system properties** (`ColorScale`, `MainScale`, `PostScale`,
  `StartSizeRange`, `LifetimeRange`, …) — arrays of ranges/structs not yet decoded. These are
  the bulk of the remaining 4% and only matter for particle effects.
- ~~**Array properties** / **enum bytes**~~ — done in Step 6 via the class schema (`schema.json`).
- ~~**Editor-brush geometry**~~ — **done in Step 6**: `Model → Polys → FPoly` decodes to
  byte-identical `Begin Brush` blocks.
- **Built-BSP volume models** (~31/554 in DM-Rankin) — Volume actors whose `Model` carries a
  *built* BSP (non-empty `Nodes`/`Surfs`/`Verts`), not a simple editor brush. We emit the
  actor but skip its polygon block (parsing `FBspNode`/`FBspSurf`/`FVert` is a larger job and
  the engine rebuilds volumes anyway).
- **`Region` (PointRegion)** kept raw and omitted from T3D — the engine recomputes it on build.
- **Emitter particle-system** structs/ranges — niche, the bulk of the remaining non-brush gap.
- **Level BSP / lightmaps / terrain heightmaps** remain opaque (per CLAUDE.md) — the T3D
  pipeline rebuilds these in-engine, so we never need to hand-decode them for the write side.

---

## Toolchain — UT2004 + UnrealEd is installed ✅

A full retail install is present at **`C:\UT2004\System`**, which **unblocks Steps 4–5**:
- **`UCC.exe`** — command-line tool. Verified working. Useful subcommands:
  - `ucc batchexport <map.ut2> Level T3D <outdir>` — export a map's `Level` to **T3D**
    (our reference for the write format). `ucc analyzecontent <map>` loads/validates a map.
- **`UnrealEd.exe`** — GUI editor for the finalize step (Build Geometry → Build Lighting → Save).
- The install's `Maps/` has all 44 stock maps, so `ucc` resolves them by name (no copying needed).

**Reference T3D:** `ucc batchexport DM-Rankin.ut2 Level T3D <dir>` produced `myLevel.T3D`
(~3.2 MB). It's git-ignored (regenerable) but is the format spec for Step 4. Confirmed it
matches our decoded properties exactly. Key format facts learned from it:
- Blocks: `Begin Actor Class=<C> Name=<N>` … indented `Prop=Value` … `End Actor`.
- `Location=(X=..,Y=..,Z=..)`, `Rotation=(Pitch=..,Yaw=..,Roll=..)` — **default/zero
  components are omitted** (e.g. `Rotation=(Yaw=-35840)`, `DrawScale3D=(Y=2.000000)`).
- Object refs are fully qualified: `StaticMesh'DM-Rankin.houreventthing'`.
- `Region=(Zone=ZoneInfo'…',iLeaf=647,ZoneNumber=9)` — confirms the `PointRegion` struct
  layout (Zone objref + iLeaf int + ZoneNumber byte) we currently keep raw.

---

## Roadmap

### Step 5 — Round-trip in UnrealEd  ← **VERIFIED ✅**
Imported `import_kit/DM-Rankin-PlayerStarts.t3d` into UnrealEd via clipboard paste (the
`.t3d` text *is* UnrealEd's actor paste format; there's no `ucc` T3D-import subcommand).

**Result — the read → decode → generate → import path works:**
- **Tools → Search for Actors** (UnrealEd's actor list) showed all **16** pasted actors,
  `PlayerStart0`–`PlayerStart15`. (The Actor Properties title showed "18 selected" only
  because Select All also grabbed the level's 2 default actors — `LevelInfo` + builder brush.)
- Spot-check `PlayerStart8`: **Rotation Yaw = 45056 — exact match.** Location read
  (3488, −352, 79) vs our authored (3456, −384, 47) = a **uniform +32 on every axis**.
  That offset is **UnrealEd's paste nudge** (one grid unit = 32), applied identically to all
  actors, so the relative layout is pixel-perfect. Not a generator bug — rotation fidelity
  and the uniform shift confirm the coordinates are correct.

To land at exact absolute positions: set the drag-grid to 1 before pasting, or paste into the
source map (overlay test) where actors drop onto the originals.

**Import kit** lives in `import_kit/` (`DM-Rankin-PlayerStarts.t3d`,
`DM-Rankin-Lights.t3d`, `README.md`).

### Step 6 — Close gaps for a fuller round-trip  ← **mostly done**
- ✅ Decode **array** properties (`PathList`/`ReachSpec`, `Skins`) and resolve **enum-byte**
  names — via `schema_extractor.py` + `schema.json` (87% → 96% non-brush T3D coverage).
- ✅ Emit **editor-brush geometry** (`Begin Brush … Begin Polygon …`) — byte-identical to the
  engine; the big one for rebuilding actual level geometry, not just actor placement.
- ☐ **Built-BSP volume models** (`FBspNode`/`FBspSurf`/`FVert`) — ~31/554 models; low priority.
- ☐ **Emitter particle-system** structs/ranges — niche.
- ☐ Programmatic generation/modification beyond reshuffling existing actors (the original
  end-goal). With read + faithful T3D write in place, this is now the natural next direction:
  e.g. round-trip a whole map's brushes through UnrealEd, or procedurally edit actor/brush data.

### Step 7 — Whole-map brush round-trip (suggested next)
Generate full-map T3D (actors + brushes), import into a fresh UnrealEd level, **Build
Geometry → Build Lighting**, and confirm the rebuilt level matches the original. This
exercises the brush pipeline end-to-end (vs. the actor-only Step-5 verification).

---

## Reference resources
- **shrimpza/unreal-package-lib** (GitHub, Java) — best reference for compact-index decoding,
  table walking, tagged-property reading. Model the Python parser on it.
- **BeyondUnreal Wiki — "Package File Format"** — header, tables, compact index, data types.
- **EliotVU — "Unreal Package File Format"** — additional header/format detail.

---

## Repo map
- `Maps/` — 39 stock UT2004 DM maps (`.ut2`, binary Unreal packages).
- `ut2parser.py` — binary reader, property decoder, JSON model, diff, full-map T3D generator,
  brush/BSP decoder, CLI (Steps 1–7).
- `schema_extractor.py` + `schema.json` — class schema (enum/array/export/static types) from
  UnrealScript (Steps 6–7).
- `navanalysis.py` — bot-pathing / inventory pattern analysis across all maps (Step 8).
- `NAV_PATTERNS.md` — bot-pathing & inventory findings (Step 8).
- `import_kit/` — Step-5 UnrealEd import kit (clean T3D subsets + paste instructions).
- `CLAUDE.md` — durable project context & format notes (in main repo root).
- `PROGRESS.md` — this file: status + roadmap.
- `uc_export/`, `reference_t3d/`, `out_t3d/` — git-ignored generated/derived data
  (regenerate via `ucc batchexport` / `--t3d`; see commands below).

## How to run
```sh
python ut2parser.py Maps/DM-Rankin.ut2              # summarize one map
python ut2parser.py Maps/*.ut2 --top 10            # summarize many
python ut2parser.py Maps/DM-Gael.ut2 --actors      # placed actors w/ location+rotation
python ut2parser.py Maps/DM-Gael.ut2 --json        # actor model as JSON
python ut2parser.py --diff Maps/DM-Rankin.ut2 Maps/DM-Gael.ut2   # per-class delta
python ut2parser.py Maps/DM-Rankin.ut2 --t3d > out.t3d           # generate full-map T3D
python ut2parser.py Maps/DM-Rankin.ut2 --t3d --t3d-class Light   # one class only

python navanalysis.py Maps/*.ut2                                 # bot-path/inventory report
python navanalysis.py Maps/*.ut2 --json                          # per-map data

# Regenerate the engine reference T3D (needs the install) for diffing:
#   cd C:\UT2004\System && ./UCC.exe batchexport DM-Rankin.ut2 Level T3D <outdir>

# Rebuild schema.json from the game's UnrealScript (needs the install):
#   cd C:\UT2004\System
#   for p in Core Engine UnrealGame XGame Gameplay XPickups XWeapons XEffects; do
#     ./UCC.exe batchexport $p.u Class UC <repo>\uc_export ; done
#   python schema_extractor.py uc_export -o schema.json
```
