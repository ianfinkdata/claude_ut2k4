# Plan — "Deathmatch in a Monster Base" (procedural, modular)

A living implementation plan for turning the read/write pipeline (see
[PROGRESS.md](PROGRESS.md), [CLAUDE.md](CLAUDE.md)) into a **procedural, modular
map generator** for a custom game concept:

> **Deathmatch, but in the middle of a monster base.** One-time-spawn monsters
> live in the level. Players play DM while unlocking progression through the map;
> the reward for progressing is access to increasingly better weapons and
> power-ups (e.g. the Redeemer locked behind a door guarded by 5 Warlords).

Last updated: 2026-06-19 (survey wave complete — see "Survey wave — RESULTS").

---

## Locked decisions

| Decision | Choice | Consequence |
|---|---|---|
| **Monster + locked-progression mechanics** | **Map-only (no UnrealScript)** | Doors via `Mover`+`Trigger`+`Counter` chains. Monster spawning/AI under DM is the open risk — see the feasibility spike (Agent 6). |
| **Art / theme family** | **Tech / industrial** | Chrome/Futuretech/metal — the family already applied to the playtest room. Cartographers default their palettes to this cluster. |

### Map-only risk (must be retired early)
Mover/Trigger/Counter door gating is proven and works without code. The unproven
part is whether a **placed monster pawn spawns and runs AI under the DM
gametype** (stock UT2004 drives monster AI from the Invasion controller). If the
spike (Agent 6) shows monsters stay inert in DM, STOP and escalate to the user
with the failure detail and the smallest fallback — do not silently switch to a
code path.

**SPIKE VERDICT (2026-06-19):** map-only monsters in DM are **very likely to
work** — confirmed at the UnrealScript source level. A placed `SkaarjPack.Monster`
self-spawns+possesses its own `MonsterController` in `PostBeginPlay()` with no
gametype check; DM (`xDeathMatch`) is not a `TeamGame` so the known team-imbalance
bug shouldn't apply. **Still pending a human in-engine confirmation run** (see
`MONSTER_GATING.md` + `import_kit/MonsterGate-Spike.t3d`). The least-certain element
is the brush-based Mover importing via raw T3D paste — if the door misbehaves but
monsters+Counter work, that's a door-authoring fix, not a feasibility failure.

---

## Survey wave — RESULTS (2026-06-19)

All six agents complete. Artifacts (re-runnable scripts + JSON + markdown) live in
`surveys/` and the repo root. Headline outputs the generator (Agent #7) consumes:

- **Textures** (`TEXTURE_PATTERNS.md`): stock-tech center is the
  **HumanoidArchitecture / AbaddonArchitecture** family — NOT the playtest room's
  Chrome/Futuretech (each in only 1 stock map). Generator supports two palette
  modes: stock-fidelity (Humanoid core) vs playtest-match (chrome hero surfaces on
  Humanoid base). Surface poly split stable: ~15-20% floor / 60-72% wall / 10-20%
  ceiling — budget texture variety to walls.
- **Lighting** (`LIGHTING_PATTERNS.md`): parametric rig — ~1 light / 300×300uu cell
  (`clamp(round(W*L/90000),6,18)`), inset ~128uu, mounted ~180uu high, `LT_Steady`,
  brightness ~90, 88% colored (warm-amber dominant + cool accents). **`LightRadius`
  is in 25-uu units** (reach = radius×25).
- **Static meshes** (`MESH_PATTERNS.md`): tech kit = ShiptechHardware +
  Humanoid/Abaddon/AlleriaHardware + Pipe_Static + 2k4ChargerMeshes (pickup bases,
  37/39 maps). Roles trim ~48% / structural ~24% / prop ~26%. **Yaw snaps to 90°;
  default scale is the norm** (stretch only for structural spans).
- **Pickups/pathing** (`NAV_PATTERNS.md` deep-dive section, `pickup_coords.json`):
  **Redeemer = canonical trophy** — peripheral (centrality 0.80), high (elev 0.90),
  farthest item from spawn (~1,400uu): the exact signature for gated reward vaults.
  Powerups = central/contested raised pedestals; armor = mid-tier, spread.
  Pickup↔InventorySpot is an exact `myMarker` link (not proximity). Walk-gap real
  target: median ≈390 / P90 ≤800 (max crowds the 1,199 ceiling but typical is far
  lower).
- **Geometry/rooms** (`ROOM_PATTERNS.md`): **grid unit = 128uu** (revised from 256),
  **256uu (2×2) default room cell**; **doorway port = 256×256uu floor-flush opening,
  grid-aligned, offset k×128uu**. Stock room sides median 256/512uu; ceiling median
  272uu; corridor median 128uu. 0/2982 subtract brushes rotated → footprints exact.
  Caveat: 6 terrain/mesh-built maps yield little CSG data (follow-up parser work).
- **Gameplay** (`MONSTER_GATING.md`, `MonsterGate-Spike.t3d`): see SPIKE VERDICT
  above + the code-free Mover/Trigger/Counter gating recipe and the gating schema
  for Agent #7.

### Cross-agent reconciliations to fold into the generator
- The lighting agent's hand-curated "tech maps" list and the texture agent's theme
  clusters must be unified into **one canonical tech-cluster definition**.
- Mesh roles are heuristic (package/Group/keyword), not geometry-verified; a future
  pass can correlate mesh `Location` vs decoded brush polys for ground truth.

---

## Current state (entering this plan)

- **Read side:** `ut2parser.py` decodes header/tables/properties/brush geometry
  for all 39 stock maps; byte-identical T3D for actors + editor brushes.
- **Write side:** T3D → UnrealEd → `.ut2` round-trip validated both for a
  full-map replica (`replica/DM-Rankin-Replica.ut2`) and a from-scratch single
  room (`gen_testmap.py` → `import_kit/TestMap-Skeleton.t3d`).
- **Data:** `navanalysis.py` + `NAV_PATTERNS.md` (nav/inventory invariants);
  `PARAM_SCHEMA.md` (tunable generator knobs, incl. the hard `walk_gap < 1200uu`
  rule).
- **Playtest room** (`Maps/claude_test_skeleton.ut2`, user-modified): the Step-9
  skeleton, now **textured + lit** (refs to `Walls`/`Chrome_cp`/`Futuretech1`/
  `Base`; `concrete1c`, `cp_chromebase1`, `cp_chrometechwallshad` shader), a
  second light rig (10 `Light`s), a second platform pair, and `Camera` actors.
  **Note:** parsed 195 exports / 40 placed actors — **no monster pawns are
  present in the saved package** (DM has nothing to own them, so they did not
  serialize). Retiring the map-only monster risk is therefore prerequisite to
  the whole concept.

---

## Architecture — everything is a Room Module

A **Room Module** is a self-contained T3D fragment with:
- a fixed **footprint** on a grid (unit TBD by Agent 5, candidate 256uu),
- **doorway "ports"** at known coordinate offsets so modules snap together,
- a **theme tag** → texture palette + light rig + mesh set (default: tech),
- a **gameplay manifest** → pickup slots, monster-spawn slots, and lock/reward
  role (e.g. "Redeemer reward, gated by 5 Warlords"),
- nav coverage satisfying `walk_gap < 1200uu` and out-degree ≈ 4.

The module library is the shared currency: cartographers (Agents 1–6) fill it
with rules and palettes; the generator (Agent 7) consumes it.

### Two outputs from one library (the /goal)
1. **Connected playable map** — modules stitched via shared ports into one
   navigable level.
2. **The "museum"** — every module duplicated on an isolated, walled-off,
   unreachable grid, so a human can funtest each room in isolation and "stamp"
   it before it is promoted into the playable map.

---

## Agent roster

Each **cartographer's DoD is a committed, re-runnable analysis script + JSON
dataset + a short markdown of rules** (the `navanalysis.py` / `NAV_PATTERNS.md`
pattern) — regenerable data that feeds the generator, not throwaway reports.

| # | Agent | Purpose | Definition of Done | Depends on |
|---|---|---|---|---|
| 1 | **texture-cartographer** | Survey texture/material/shader packages + per-surface usage across 39 maps; cluster themes; recommend the tech palette. | `surveys/texture_survey.py` + `textures.json` + `TEXTURE_PATTERNS.md`: package→texture→frequency, co-occurrence/theme clusters, recommended tech palette per module theme. | — |
| 2 | **lighting-cartographer** | Survey `Light` actors: LightType/Effect, brightness, hue/sat, radius, falloff, count-per-volume, placement vs geometry. | `surveys/lighting_survey.py` + `lighting.json` + `LIGHTING_PATTERNS.md`: distributions + a parametric light-rig rule per room size/theme. | — |
| 3 | **staticmesh-cartographer** | Survey `StaticMeshActor` usage: mesh packages, frequency, scale/rotation dists, co-occurrence, relation to brush geometry. | `surveys/mesh_survey.py` + `meshes.json` + `MESH_PATTERNS.md`: mesh palette + placement rules (trim vs prop vs structural). | — |
| 4 | **pickup-pathing-cartographer** | Deep coordinate dive on pickups + bot pathing (extends `navanalysis.py`): pickup placement vs geometry, nav-node spatial distribution, weapon/powerup anchoring (the reward-gating data). | Extended `navanalysis.py` + `pickup_coords.json` + `NAV_PATTERNS.md` additions: coordinate-level placement rules, esp. high-value weapons/powerups. | — |
| 5 | **geometry/room-cartographer** | Survey room/brush structure: footprints, corridor widths, **doorway dimensions**, ceiling heights, connectivity — the spatial backbone for snap-together modules. | `surveys/geometry_survey.py` + `geometry.json` + `ROOM_PATTERNS.md`: footprint/doorway/height dists → the module grid unit + port spec. | — |
| 6 | **gameplay-systems agent** (owns the map-only mechanics) | Retire the map-only risk + define the gating schema. **First task: feasibility spike** — one room, a few monsters, one Counter-gated Mover door revealing one weapon, tested in-engine under DM. | Spike result writeup (do monsters tick under DM? y/n + evidence) **and**, if yes, a working vertical-slice T3D + the monster-spawn-slot / lock / reward schema modules embed. If no: escalate with fallback options. | — |
| 7 | **module-assembler / generator** (synthesis) | Extend `gen_testmap.py` into a modular room-graph generator consuming all cartography outputs + `PARAM_SCHEMA.md`; emit the connected map **and** the museum. | `gen_map.py`: multi-room T3D from the module library; validates `walk_gap<1200` + out-degree≈4; emits both layouts; passes `ucc analyzecontent` (0 errors). | 1–6 |

Round-trip QA (UnrealEd Build + `ucc analyzecontent` + the
[manual_instructions.md](manual_instructions.md) checklist, computer-use driven)
stays a shared responsibility unless we decide to split it out.

### Sequencing
- **Parallel wave (front-loaded):** Agents 1–6 are independent — 1–5 are
  read-only surveys over `Maps/*.ut2`; 6 is an in-engine spike. Run together.
- **Convergence:** Agent 7 starts once 1–6 land and is where the module library
  becomes a generator.

---

## Open items / TBD (refine with user)
- ✅ RESOLVED — Module grid unit: **128uu**, with a **256uu (2×2) room cell**;
  doorway port = **256×256uu** floor-flush, offset k×128uu (Agent 5).
- ✅ RESOLVED (pending human run) — monster classes are placeable/functional under
  DM; classes live in `SkaarjPack.u`; gating recipe in `MONSTER_GATING.md` (Agent 6).
- **NEXT — human action:** run the in-engine confirmation of
  `import_kit/MonsterGate-Spike.t3d` per the 5 CHECKs in `MONSTER_GATING.md`.

**Design rules from playtest (2026-06-19):**
- **Doors = static-mesh Movers, not brush Movers.** A `Mover` with
  `DrawType=DT_StaticMesh` + `StaticMesh='…'` is a pure-property actor (like
  StaticMeshActor, which imports 664/664) → it **survives T3D paste reliably**,
  unlike brush-Movers whose inline brush model the importer won't rebuild. This is
  both the spike door fix AND the generator's door strategy (emit doors fully in
  T3D). Caveat: confirm the chosen door mesh has solid collision (or back it with a
  blocking volume). Candidate mesh: `cp_Mechstaticpack1.Doors.cp_lp_Mechdoorway1`.
- **Gate-encounter rooms carry a combat loadout, not just the gated prize.** Three
  Warlords vs. a starting Assault Rifle is unfair. Each gate/arena room must include
  baseline weapons + ammo + health so players can actually fight the guardians; the
  gated reward (Redeemer-tier) is *on top* of that. Generator: a gate room's pickup
  manifest = combat loadout (placed per the `NAV_PATTERNS.md` weapon/ammo/health
  rules) + the locked trophy behind the door.
- Monster **counts per reward tier** (e.g. "5 Warlords → Redeemer") — design choice,
  still to set with user.
- Texture palette mode: stock-fidelity (Humanoid) vs playtest-match (chrome) — pick
  with user before generator theming.
- Whether round-trip QA becomes its own agent (#8).
- Module manifest file format (JSON schema for footprint/ports/slots/theme) — define
  at the start of Agent #7.
