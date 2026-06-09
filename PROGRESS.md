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

## Current status: **Step 2 complete — actors decode**

We can parse every stock map, enumerate its objects, **and recover each placed actor's
properties** (class, location, rotation, key settings).

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
    and the `Vector`/`Rotator`/`Color` structs; anything else is kept as raw bytes with
    exact realignment so the stream never desyncs.
  - CLI: `--summary` (default) and `--actors` (placed-actor list with location/rotation).
- **Verified against all 39 stock DM maps:**
  - Tables: 0 failures, every object reference resolves, one `Level` per map. Versions 18×v127, 21×v126.
  - Properties: every export in every map decoded — **0 errors, 63,981 placed actors** recovered.

### What parses cleanly today
Header, name/import/export tables, the **full object inventory**, and the **per-actor
property set** — class, `Location`, `Rotation`, names, object refs, scalars, and the common
structs. Output reads exactly like a real DM map (`StaticMesh="houretrim"`, `Light` with
`LightBrightness`, `PathNode` nav lists, etc.).

### Known limitations / not yet decoded
- **Some struct/array values are kept raw** — `Region` (PointRegion), `PathList`/`ReachSpec`
  arrays, `Scale`, etc. We skip them correctly but don't interpret them yet. Easy to extend
  per struct as needed.
- **Geometry blobs** (BSP tree, brush polys, lightmaps, terrain heightmaps) remain opaque.
  Per CLAUDE.md these aren't fully public; we read their metadata, not their contents — and
  the T3D pipeline means we never need to hand-decode them for the write side.

---

## Roadmap

### Step 3 — Structured export (JSON) + map diff  ← **next**
Emit the parsed actor list as JSON: every actor with its class and recovered properties,
ready as input to the write side and for diffing two maps. Optionally interpret the
remaining structs (`Scale`, `PointRegion`) and decode array element types.
**Outcome:** a machine-readable actor model per map.

### Step 4 — T3D generation (write side)
Generate **T3D** text from the parsed/transformed actor data. Start with actor-only T3D
(placement of existing meshes/lights/pathnodes), since brush geometry is the hard part.
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
- `ut2parser.py` — the binary package reader, property decoder + CLI (Steps 1–2).
- `CLAUDE.md` — durable project context & format notes (in main repo root).
- `PROGRESS.md` — this file: status + roadmap.

## How to run
```sh
python ut2parser.py Maps/DM-Rankin.ut2          # summarize one map
python ut2parser.py Maps/*.ut2 --top 10         # summarize many
python ut2parser.py Maps/DM-Gael.ut2 --actors   # list placed actors w/ location+rotation
```
