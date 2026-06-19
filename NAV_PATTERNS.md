# UT2004 DM — Bot-Pathing & Inventory Patterns

Mined from all 39 stock Deathmatch maps with `navanalysis.py` (built on `ut2parser`).
These are the **repeatable rules** behind how the stock maps wire up bot navigation and
item placement — the raw material for procedurally generating or modifying a map's AI graph.

Run it yourself: `python navanalysis.py Maps/*.ut2`  (add `--json` for data).

---

## The navigation graph in one paragraph

A map's bot AI is a directed graph: **NavigationPoint** nodes (PathNode, InventorySpot,
JumpSpot, PlayerStart, LiftCenter/Exit…) joined by **ReachSpec** edges. Each ReachSpec stores
`Start`, `End`, `Distance`, `CollisionRadius/Height` (the biggest pawn that fits), a
`reachFlags` bitmask (how the edge is traversed), and `bForced`. A node's `PathList` holds its
outgoing edges. The engine rebuilds this whole graph from node placement via **Build AI Paths**
— which is exactly why it's safe for our T3D pipeline to omit ReachSpecs and let the engine
regenerate them.

`reachFlags` bits: `walk=1, fly=2, swim=4, jump=8, door=16, special=32, ladder=64,
proscribed=128, forced=256, playeronly=512`.

---

## Cross-map invariants (39 maps)

| Metric | Value | Reading |
|---|---|---|
| avg nav nodes / map | **193** | |
| avg ReachSpec edges / map | **820** | |
| **avg out-degree** | **4.2** (max ~12) | every node links to ~4 neighbours — a deliberate connectivity target |
| **InventorySpot : pickup ratio** | **1.00** | **exactly one InventorySpot per pickup** — the strongest rule in the set |
| avg PlayerStarts / map | **15.9** | DM maps are built for ~16 players regardless of size |
| edge-type mix | **82% walk, 14% jump, 1% forced, 1% special** | remarkably constant across every map |
| dominant path collision size | radius **120**, height **100–120** | paths cut for a generous (large-pawn) capsule |

Pickup category totals across all maps: **ammo 800, health 621, adrenaline 369, weapon 308,
armor 63, powerup 29** — i.e. maps are dominated by ammo + health, with weapons and a couple of
power-ups as the "anchors."

---

## Repeatable sub-structures (the generation rules)

### 1. Pickup anchoring — *1 pickup ⇒ 1 InventorySpot*
Every pickup actor has an **InventorySpot dropped at its base** (matched within ~15–65uu, just
floor-snapped). The InventorySpot — not the pickup — is the navigation node bots path to.
> **Rule:** to place a bot-reachable item, spawn the pickup *and* an `InventorySpot` at the
> same X,Y on the floor below it; wire the InventorySpot into the nearby graph.

### 2. PathNode mesh — *connectivity, not coverage*
PathNodes are placed so the resulting ReachSpecs keep out-degree ≈ 4 and walk-edge length
under ~1200uu (avg ~450–520uu). They're laid along walkable routes and at junctions, not on a
uniform grid.
> **Rule:** drop PathNodes at corridor junctions / direction changes and along long runs so no
> walkable gap exceeds ~1000–1200uu; the engine fills in the edges.

### 3. Jump links — JumpSpot + jump edges (~14% of all edges)
Vertical / gap traversal uses `JumpSpot` nodes connected by **R_JUMP (8)** ReachSpecs, often
`bForced`/**R_FORCED (256)** for jump-pad style one-way boosts. ~14% of every map's edges are
jumps; forced edges are ~1%.

### 4. Lift networks — a clean, taggable template
A lift is a fixed cluster:
- a **Mover** (the platform brush),
- one **LiftCenter** sitting on the platform (`MyLift` → the Mover),
- N **LiftExit** nodes, one at each floor the lift serves,
- all sharing a **`LiftTag`**, and
- **bidirectional R_SPECIAL (32)** ReachSpecs between the LiftCenter and every LiftExit.

> **Rule (parametric lift):** `Mover + LiftCenter + LiftExit×floors`, tie them with a shared
> `LiftTag` and point each at the Mover; the special edges then connect center↔exits both ways.

---

## What this unlocks

- **Procedural AI graphs:** place nodes by the rules above, emit them in T3D, and **Build AI
  Paths** generates the ReachSpecs — no need to author edges by hand.
- **Map validation:** flag pickups with no InventorySpot, nodes with out-degree < 2 (likely
  unreachable), or walk gaps > 1200uu (bots may fail to path).
- **Style transfer:** the invariants (16 spawns, 1:1 pickup anchoring, ~4 connectivity,
  ammo/health-heavy economy) are a recipe for "feels like a stock UT2004 DM map."

See `navanalysis.py` for the metrics and `--json` for the per-map data behind every number here.

---

# Coordinate-level placement rules (deep dive)

Added by the pickup-pathing-cartographer (Agent #4). Source:
`surveys/pickup_coords.py` (re-runnable, `--json`) → `surveys/pickup_coords.json`.
Pooled over **2,194 pickups across all 39 stock maps**. Pickup↔InventorySpot
matching is **exact**, not proximity: every pickup carries `myMarker` → its
InventorySpot (100% coverage), confirming the 1:1 rule at the actor-link level.

Two normalised frames are used throughout:
- **centrality** ∈ [0,1]: XY distance from the map's nav centroid ÷ map radius
  (0 = dead-centre, 1 = at the outer edge of the nav bounding box).
- **elev_norm** ∈ [0,1]: (Z − floor) ÷ (Z-range) (0 = lowest floor, 1 = top of
  the vertical extent).

## A. Pickup anchoring is sub-floor-snapped, not on-floor

The InventorySpot is **not** at the pickup's origin — it is dropped at the
pickup then floor-snapped to pawn-centre height, so it sits a fixed amount
*above* the pickup mesh base. Measured `pickup_Z − spot_Z` (median):

| Category | z_above_spot (med) | dist pickup→its spot (XY) |
|---|---|---|
| weapon  | **−42 uu** | ~0 (directly below) |
| armor   | **−41 uu** | ~0 |
| powerup | **−41 uu** | ~0 |
| ammo    | **−33 uu** | ~0 |
| health  | **−23 uu** | ~0 |
| adrenaline | **−23 uu** | ~0 |

> **Rule:** place the pickup actor at floor level, then put its InventorySpot at
> the *same XY* but **+23 uu (small pickups) to +42 uu (weapon/armor/powerup
> bases)** in Z. The class-specific offset just reflects collision-cylinder
> height; the engine sets it on Build AI Paths, so a generator can simply
> co-locate spot and pickup in XY and let the snap happen.

`dist_nearest_nav` (pickup → nearest nav node) is essentially this same offset:
weapon/armor/powerup cluster at **41–42 uu**, small pickups at **23–33 uu** —
i.e. the nearest node to any pickup is virtually always *its own* InventorySpot.

## B. Spacing / clustering — weapons and armor are deliberately spread

Nearest-**same-category** pickup distance (median) is the clean spacing signal:

| Category | nearest same-category (med) | reading |
|---|---|---|
| ammo / health | ~115–128 uu | tightly packed (often ammo beside its weapon) |
| adrenaline | ~141 uu | small clusters / trails |
| weapon | **~1,065 uu** | weapons are spread across the map, ~1 per region |
| armor | **~2,657 uu** | the 1–2 armor pieces sit far apart |

> **Rule:** ammo/health/adrenaline may cluster (gaps ~100–150 uu); **weapons
> must be ≳ 800–1,100 uu apart** (p25 ≈ 800 uu) and the few armor pieces ≳
> 1,600 uu apart. No two weapon spawns share a room corner.

## C. HIGH-VALUE anchoring (the reward-gating inputs)

This is the key output for the monster-base concept. Regular weapons/armor/
powerups are spread fairly evenly (centrality ≈ 0.5–0.6, elevation ≈ 0.4–0.6
— i.e. mid-map, mid-height). The **premium** items break that pattern:

| Item | n | centrality (med) | elev_norm (med) | dist→spawn (med) | dist→wall (med) |
|---|---|---|---|---|---|
| **Redeemer** | 8 | **0.80** (peripheral) | **0.90** (near top) | **1,403 uu** (farthest) | 727 uu (open) |
| Painter | 2 | 0.40 | 0.40 | 1,599 uu | 80 uu (tucked) |
| any weapon (baseline) | 312 | 0.60 | 0.40 | 666 uu | 294 uu |
| powerup (UDamage/SuperShield/etc.) | 29 | 0.50 | **0.60** (raised) | 813 uu | 273 uu |
| armor | 63 | 0.60 | 0.40 | **1,023 uu** | 347 uu |

Weapon-type counts across the set: RocketLauncher 48, LinkGun 44, ShockRifle
44, Minigun 44, FlakCannon 42, SniperRifle 36, BioRifle 35, **Redeemer 8**,
ClassicSniperRifle 4, **Painter 2**, ONSGrenadeLauncher 1.

> **Reward-gating rules (premium items):**
> - **Redeemer** is the canonical "trophy": **elevated** (top ~90% of the
>   vertical extent), **peripheral** (centrality ≈ 0.8, toward a map corner/edge),
>   and **the farthest item from any spawn** (~1,400 uu). Place reward weapons
>   on an upper, edge-of-map platform reached by lift/jump — exactly the geometry
>   a Counter-gated Mover door fronts.
> - **Powerups** (UDamage / SuperShield) sit **raised** (elev ≈ 0.6) but more
>   central (≈ 0.5) and contested — exposed pedestals, not tucked corners.
> - **Armor** is the most spawn-distant of the *common* items (~1,023 uu) and
>   maximally spread (≥1,600 uu apart): treat as a mid-tier reward, not a
>   spawn-adjacent freebie.
> - Premium weapons sit in **open** space (Redeemer dist-to-wall 727 uu) so the
>   approach is contestable; only the Painter is tucked against a wall (80 uu).

## D. Nav-node spatial distribution

- **Per-floor density:** binning nav nodes into 256 uu Z-bands, the median band
  holds **~32 nodes** (p25 14, p75 55, max 191). Node coverage tracks where the
  playable floor is, not a uniform 3-D fill — most nodes live in 1–2 dominant
  bands with thin coverage on upper ledges.
- **InventorySpot graph integration:** InventorySpot mean out-degree per map is
  **~3.5** (slightly below the global ~4.2 — item nodes are near-leaves on the
  graph). Out-degree distribution across all spots: 2→562, 3→596, 4→450, with a
  long tail to 13. **92 spots have out-degree 1** and **1 has out-degree 0** —
  one-way "leaf" item nodes (a pickup on a jump-pad/lift-only ledge: reached by
  an incoming forced/jump edge, with a single edge back out). This is a real
  structural pattern (item-on-a-ledge), not a defect.

> **Rule:** an InventorySpot needs only **1–2 outgoing edges**; it's allowed to
> be a leaf. A reward item on a gated upper ledge will legitimately be a
> low-out-degree node reached by a jump/lift/forced edge — don't force ~4
> connectivity on item nodes the way you do on corridor PathNodes.

## E. Realised walk-gap distribution (not just the global max)

The global "no walk gap > 1200 uu" ceiling from `PARAM_SCHEMA.md` holds, but the
*realised* distribution shows how much headroom maps actually leave:

| Per-map stat | min | median | max |
|---|---|---|---|
| **MAX** walk-gap | 1,018 | **1,188** | 1,199 |
| **P90** walk-gap | 514 | **753** | 943 |
| **MEDIAN** walk-gap | 275 | **390** | 538 |

So: every map's *longest* walk edge crowds right up against ~1,200 uu (median
max 1,188 — the ceiling is real and routinely approached), but the **bulk** of
edges are far shorter — 90% of walk edges are under ~750–900 uu, and the typical
edge is ~390 uu.

> **Rule:** target a **median walk gap ≈ 390 uu** and keep **P90 ≤ ~800 uu**;
> you may have a handful of edges up to (but never over) 1,199 uu. A generator
> that only checks the 1,200 ceiling but lets the *median* drift high will feel
> sparse — stock maps are denser than the ceiling implies.

## Data not extractable / caveats

- **Distance to wall** uses `BlockingVolume` actors as the wall proxy; not all
  maps wall off play space with BlockingVolumes (some rely on world brush/CSG),
  so `dist_nearest_wall` is *approximate* and absent on maps without them. True
  brush-face distance would need BSP/poly decoding (out of scope per CLAUDE.md).
- **Height-above-actual-floor** is reported relative to the InventorySpot (a
  reliable floor-snapped proxy), not the BSP floor surface (not decoded).
- **Elevation/centrality** are normalised to the *nav bounding box*, not true
  room geometry — a robust cross-map frame, but a tall sky-zone can stretch the
  Z-normaliser. Per-map raw Z is in the JSON if an absolute frame is needed.

