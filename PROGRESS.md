# UT2004 DM Map Project — Progress & Roadmap

A living "save state" for the project. Read this together with [CLAUDE.md](CLAUDE.md),
which holds the durable context (goal, file-format essentials, architecture decision).
This document tracks **where we are and what's next**.

Last updated: 2026-06-08

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

## Current status: **Step 5 complete — round-trip verified in UnrealEd ✅**

The full **read → decode → generate-T3D → engine-import** loop is proven end-to-end: 16
generated PlayerStarts pasted into UnrealEd with exact rotation and correct (grid-offset)
placement. We can parse every stock map, recover each placed actor's properties, export a
JSON model, generate actor-placement T3D that matches the engine's own export, and import
it back into the editor.

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
  - CLI: `--summary` (default), `--actors`, `--json` (`--all-objects`), `--diff A B`,
    and `--t3d` (`--t3d-class C` to restrict to a class).
- **Verified against all 39 stock DM maps:**
  - Tables: 0 failures, every object reference resolves, one `Level` per map. Versions 18×v127, 21×v126.
  - Properties: every export in every map decoded — **0 errors, 63,981 placed actors** recovered.
  - JSON: all 39 maps emit valid, parseable JSON.
  - T3D: all 39 maps emit well-formed T3D (balanced blocks, no unresolved refs). Diffed
    against the engine reference for DM-Rankin: **all 664 `StaticMeshActor` blocks match
    exactly** (ignoring deferred arrays); ~87% of non-brush actor property-lines reproduced
    verbatim. The gap is entirely deferred categories (below).

### What parses cleanly today
Header, name/import/export tables, the **full object inventory**, the **per-actor property
set** (class, `Location`, `Rotation`, `DrawScale`/`DrawScale3D`, names, refs, scalars, common
structs), and a **JSON actor model** ready for transform/diff. Output reads exactly like a
real DM map (`StaticMesh="houretrim"`, `Light` with `LightBrightness`, `PathNode` nav lists).

### Known limitations / not yet decoded
- **Array properties** (`PathList`, `Skins`, `Actions`, emitter ranges) — read past correctly
  but kept raw, so not yet emitted to T3D. `PathList`/`ReachSpec` is the bot-nav graph; the
  engine can rebuild it (Build Paths), so it's optional for a first round-trip.
- **Enum bytes** (`LightEffect`, `DetailMode`, `Physics`, …) decode to their numeric index;
  we don't have the enum name tables, so T3D shows the number instead of e.g. `LE_NonIncidence`.
  Plain bytes (`SoundVolume`) are fine.
- **`Region` (PointRegion)** kept raw and omitted from T3D — the engine recomputes it on build.
- **Brush/BSP geometry** (`Begin Brush … Begin Polygon …`, `CsgOper`, `MainScale`) is not
  emitted: Brush actors appear with their transform but without their polygon definitions.
  This is the deferred geometry work and the main thing standing between us and a *complete*
  map rebuild (vs. an actor-placement rebuild).
- **Geometry blobs** (BSP tree, brush polys, lightmaps, terrain heightmaps) remain opaque.
  Per CLAUDE.md these aren't fully public; we read their metadata, not their contents — and
  the T3D pipeline means we never need to hand-decode them for the write side.

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

### Step 6 — Close gaps for a fuller round-trip
As needed for the target use case:
- Decode **array** properties (esp. `PathList`/`ReachSpec`) and **enum-byte** name tables.
- Emit **brush/BSP** geometry (`Begin Brush … Begin Polygon …`) — the big one for rebuilding
  actual level geometry rather than just actor placement.
- Programmatic generation/modification beyond reshuffling existing actors.

---

## Reference resources
- **shrimpza/unreal-package-lib** (GitHub, Java) — best reference for compact-index decoding,
  table walking, tagged-property reading. Model the Python parser on it.
- **BeyondUnreal Wiki — "Package File Format"** — header, tables, compact index, data types.
- **EliotVU — "Unreal Package File Format"** — additional header/format detail.

---

## Repo map
- `Maps/` — 39 stock UT2004 DM maps (`.ut2`, binary Unreal packages).
- `ut2parser.py` — binary reader, property decoder, JSON model, diff, T3D generator, CLI (Steps 1–4).
- `import_kit/` — Step-5 UnrealEd import kit (clean T3D subsets + paste instructions).
- `CLAUDE.md` — durable project context & format notes (in main repo root).
- `PROGRESS.md` — this file: status + roadmap.

## How to run
```sh
python ut2parser.py Maps/DM-Rankin.ut2              # summarize one map
python ut2parser.py Maps/*.ut2 --top 10            # summarize many
python ut2parser.py Maps/DM-Gael.ut2 --actors      # placed actors w/ location+rotation
python ut2parser.py Maps/DM-Gael.ut2 --json        # actor model as JSON
python ut2parser.py --diff Maps/DM-Rankin.ut2 Maps/DM-Gael.ut2   # per-class delta
python ut2parser.py Maps/DM-Rankin.ut2 --t3d > out.t3d           # generate actor T3D
python ut2parser.py Maps/DM-Rankin.ut2 --t3d --t3d-class Light   # one class only

# Regenerate the engine reference T3D (needs the install) for diffing:
#   cd C:\UT2004\System && ./UCC.exe batchexport DM-Rankin.ut2 Level T3D <outdir>
```
