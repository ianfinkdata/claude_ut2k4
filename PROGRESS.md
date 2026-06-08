# UT2004 DM Map Project — Progress & Roadmap

A living "save state" for the project. Read this together with [CLAUDE.md](CLAUDE.md),
which holds the durable context (goal, file-format essentials, architecture decision).
This document tracks **where we are and what's next**.

Last updated: 2026-06-07

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

## Current status: **Step 1 complete — binary reader works**

We can parse every stock map and enumerate its objects.

### Done
- **`ut2parser.py`** — dependency-free Python reader for the Unreal package format.
  - `Reader` with Unreal primitives, incl. the two that bite:
    - **signed compact index** (1–5 bytes; byte 0: `0x80`=sign, `0x40`=continuation, low 6 bits value).
    - **length-prefixed FString** (compact-index length, ANSI, NUL-terminated).
  - `parse()` validates magic `0x9E2A83C1`, reads the header, and walks the
    **name / import / export** tables with full name + object-reference resolution.
  - CLI summary: version/GUID, table counts, top object classes, dependency list.
- **Verified against all 39 stock DM maps** — 0 failures, every object reference resolves,
  each map has exactly one `Level` export. Versions: 18×v127, 21×v126 (both valid UT2004).

### What parses cleanly today
Header, name/import/export tables, and the **full actor/object inventory** of any map —
class, name, outer, serial offset & size for every export; the package dependency list.
Output reads exactly like a real DM map (`myLevel`, `LevelInfo`, `Light`, `StaticMeshActor`,
`Brush`/`Model`/`Polys`, `PathNode`/`ReachSpec`/`InventorySpot` bot-nav, etc.).

### Known limitations / not yet decoded
- **Tagged-property streams** inside each export's serial data are not yet decoded — so we
  have *which* actors exist, but not their per-actor `Location`/`Rotation`/`DrawScale`/settings.
- **Geometry blobs** (BSP tree, brush polys, lightmaps, terrain heightmaps) remain opaque.
  Per CLAUDE.md these aren't fully public; we read their metadata, not their contents — and
  the T3D pipeline means we never need to hand-decode them for the write side.

---

## Roadmap

### Step 2 — Decode tagged actor properties  ← **next**
Parse the `name → type → size → value` tagged-property stream within each export's serial
data. Target the reliable, documented property types first: `Location` (Vector),
`Rotation` (Rotator), `DrawScale`/`DrawScale3D`, bools, ints, floats, names, object refs.
**Outcome:** a complete, structured actor list per map (class + transform + key settings).

### Step 3 — Richer CLI / structured export
Emit the parsed actor list as JSON (or a readable report): every actor with its class and
recovered properties. Useful as the input to the write side and for diffing maps.

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
- `ut2parser.py` — the binary package reader + CLI (Step 1).
- `CLAUDE.md` — durable project context & format notes (in main repo root).
- `PROGRESS.md` — this file: status + roadmap.

## How to run
```sh
python ut2parser.py Maps/DM-Rankin.ut2          # summarize one map
python ut2parser.py Maps/*.ut2 --top 10         # summarize many
```
