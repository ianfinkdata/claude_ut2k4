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

## Current status: **Step 3 complete — structured actor model**

We can parse every stock map, enumerate its objects, recover each placed actor's
properties, **and export a machine-readable actor model (JSON) or diff two maps.**

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
  - CLI: `--summary` (default), `--actors` (placed-actor list), `--json` (actor model;
    `--all-objects` to include non-actors), and `--diff A B` (per-class actor-count delta).
- **Verified against all 39 stock DM maps:**
  - Tables: 0 failures, every object reference resolves, one `Level` per map. Versions 18×v127, 21×v126.
  - Properties: every export in every map decoded — **0 errors, 63,981 placed actors** recovered.
  - JSON: all 39 maps emit valid, parseable JSON.

### What parses cleanly today
Header, name/import/export tables, the **full object inventory**, the **per-actor property
set** (class, `Location`, `Rotation`, `DrawScale`/`DrawScale3D`, names, refs, scalars, common
structs), and a **JSON actor model** ready for transform/diff. Output reads exactly like a
real DM map (`StaticMesh="houretrim"`, `Light` with `LightBrightness`, `PathNode` nav lists).

### Known limitations / not yet decoded
- **A few struct/array values are kept raw** — `Region` (PointRegion), and `Array` properties
  like `PathList`/`ReachSpec`/`Skins` (element type not yet decoded). Skipped correctly with
  exact realignment; easy to extend per type as needed.
- **Geometry blobs** (BSP tree, brush polys, lightmaps, terrain heightmaps) remain opaque.
  Per CLAUDE.md these aren't fully public; we read their metadata, not their contents — and
  the T3D pipeline means we never need to hand-decode them for the write side.

---

## Roadmap

### Step 4 — T3D generation (write side)  ← **next**
Generate **T3D** text from the parsed/transformed actor data. Start with actor-only T3D
(placement of existing meshes/lights/pathnodes), since brush geometry is the hard part.
The JSON actor model from Step 3 is the natural input. Map T3D's `Begin Actor Class=…
Name=… / Location=(X=..,Y=..,Z=..) / Rotation=(Pitch=..,Yaw=..,Roll=..) / End Actor`
back from the decoded properties.
**Outcome:** a T3D file UnrealEd can import.

### Step 5 — Round-trip in UnrealEd
Import generated T3D, Build Geometry → Build Lighting → save `.ut2`, and confirm the map
loads. Establishes the full read → transform → write → finalize loop.

### Later
- Brush/BSP T3D (full polygon defs) for actual level geometry.
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
- `ut2parser.py` — binary reader, property decoder, JSON model + diff, CLI (Steps 1–3).
- `CLAUDE.md` — durable project context & format notes (in main repo root).
- `PROGRESS.md` — this file: status + roadmap.

## How to run
```sh
python ut2parser.py Maps/DM-Rankin.ut2              # summarize one map
python ut2parser.py Maps/*.ut2 --top 10            # summarize many
python ut2parser.py Maps/DM-Gael.ut2 --actors      # placed actors w/ location+rotation
python ut2parser.py Maps/DM-Gael.ut2 --json        # actor model as JSON
python ut2parser.py --diff Maps/DM-Rankin.ut2 Maps/DM-Gael.ut2   # per-class delta
```
