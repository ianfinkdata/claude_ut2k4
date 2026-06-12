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
