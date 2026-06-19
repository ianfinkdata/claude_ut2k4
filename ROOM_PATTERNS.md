# Room / Brush Geometry Patterns — the Spatial Backbone

Derived from the **CSG brush geometry** of the 39 stock UT2004 DM maps via
`surveys/geometry_survey.py` (data in `surveys/geometry.json`). This is Agent
#5's deliverable for `PLAN_MONSTERBASE.md`: the **module grid unit** and the
**doorway port spec** the modular generator standardizes on.

Where `navanalysis.py` / `PARAM_SCHEMA.md` measure *playable space indirectly*
(footprint = bounding box of nav nodes, verticality = node Z spread), this
survey measures *the geometry itself*: the world-space bounding boxes of the
`CSG_Subtract` brushes that carve out the hollow spaces players move through.
The two are complementary — nav gives reachability extents, brushes give the
actual room walls/ceilings and the apertures between them.

All distances are Unreal Units (uu); 1uu ≈ 1 inch. A UT2004 pawn is ~88uu
standing, ~50uu collision radius. Reference room height is 256–512uu.

---

## Method (and why the numbers are trustworthy)

1. **Read brushes, not BSP.** Each `Brush` actor carries an editor `Model →
   Polys → FPoly` chain that `ut2parser` decodes byte-identically. We take the
   `CSG_Subtract` brushes (the hollow volumes) and ignore `CSG_Add` (solid
   fill-back) and tiny detail cuts.
2. **World-space transform.** Brush polys are in local brush space. World vertex
   = `(localVertex − PrePivot) · MainScale.Scale · PostScale.Scale + Location`.
3. **AABBs are EXACT, not approximate.** A survey-wide check found **0 / 2982**
   subtract brushes carry a non-identity `Rotation` — every stock subtract
   volume is axis-aligned. So an axis-aligned bounding box of the transformed
   vertices is the true extent, with no rotated-hull error.
4. **Filtering.** A subtract volume counts as "room-like" if its smallest
   dimension ≥ 64uu (drops trim/recess cuts) and its short horizontal side
   < 8192uu (drops the world-envelope sky/sea cube — e.g. the engine-max
   131072³ subtract; 15 such fills across all maps, reported separately).

### Coverage / honest caveat
- **2982 room-like subtract volumes** across the set; **34 / 39 maps** yield ≥10.
- **5 maps are CSG-poor** because they're built from **terrain + static meshes**
  rather than subtractive CSG: `DM-Injector` (262 subtracts, but all are detail
  cuts on a mesh-built arena), `DM-Gestalt` (7 brushes total), `DM-DesertIsle`
  and `DM-Junkyard` (outdoor terrain), `DM-1on1-Serpentine`, `DM-Curse4`. For
  these, brush geometry under-represents the real playable space — the nav-node
  footprint in `PARAM_SCHEMA.md` is the better proxy there. The recommendations
  below are anchored on the 34 CSG-built maps, which is the relevant population
  anyway (the generator emits CSG rooms, not terrain).

---

## Footprint distribution (room horizontal dimensions)

Per room-like subtract volume, sorted short/long horizontal sides:

| Metric | min | q1 | median | q3 | max* |
|---|---|---|---|---|---|
| Room **short** side | 64 | 128 | **256** | 410 | 7232 |
| Room **long** side | 64 | 256 | **512** | 896 | 18296 |
| Footprint area (short×long) | — | — | ~131k sq uu | — | — |

\*max excludes the world-envelope fills. The long-tail maxima are large arenas
(single big subtract carving a whole atrium).

**Read:** the *typical* carved volume is ~256×512uu — i.e. **2×4 units of a
128uu grid**. The bulk of rooms live in the 128–896uu band on each side. This
is a "room" in the CSG sense (one subtract); large arenas are a single big
subtract, so the median is a *segment* size, not a whole arena.

---

## Ceiling height distribution (room Z extent)

| min | q1 | median | q3 | max |
|---|---|---|---|---|
| 64 | 204 | **272** | 512 | 7872 |

Modal heights (snapped to 32uu), by frequency:

```
 256uu  ████████████████████████  (621)   <- dominant
 512uu  █████████                 (223)
 128uu  █████████                 (221)
 320uu  ███████                   (191)
 384uu  ██████                    (163)
 192uu  ██████                    (161)
  64uu  █████████                 (236)   <- mostly low detail cuts / sub-volumes
```

**Read:** **256uu is the default room ceiling** (one "story"), with **512uu the
standard tall/double-height room** and 128uu for crawlspaces/low connectors.
Heights cluster cleanly on 64uu multiples (256 = 4×64, 512 = 8×64). This mirrors
`PARAM_SCHEMA.md`'s `z_range` default of 512 (one main floor + one elevated
area) — a single room is ~256, a two-level room ~512.

---

## Corridor widths

Volumes with horizontal aspect ratio ≥ 2 (long passages); short side = width:

| min | q1 | median | q3 |
|---|---|---|---|
| 64 | 84 | **128** | 256 |

```
 corridor width (uu)
   <96    ███████████  (387)   <- 64-88uu tight squeezes / detail
  96-128  ███          (125)
 128-160  ████████     (282)   <- the standard corridor
 160-256  █████        (153)
 256-320  ██████       (225)   <- "wide hall" / two-abreast
   >=320  ███████      (293)
```

**Read:** the **standard corridor is 128–256uu wide**. 128uu comfortably passes
one pawn (~100uu collision diameter); 256uu is a two-abreast hall. Below ~96uu
are detail slots, not real passages. Generator default corridor = **256uu**
(comfortable single-file with wall clearance; safest for bot nav).

---

## Doorways / openings — what we can and can't extract

**This is the hardest item and deserves an honest accounting.**

### What is NOT directly recoverable
UT2004 door *frames* are not their own primitive. A doorway is the **absence**
of geometry — the void left where one subtract volume opens into another — and
the visible frame/trim is built from *separate additive brushes and static-mesh
trim*. There is no "Doorway" object to read. So we cannot read a labelled door
width the way we read a brush dimension.

### What IS extractable — the contact-aperture method
We derive openings geometrically: for every pair of axis-aligned subtract
volumes that **touch or overlap on a shared plane** (faces within 2uu along one
axis), the rectangle where they overlap in the *other two axes* is the aperture
connecting the two hollow spaces. Its horizontal side = opening **width**, its Z
side = opening **height**. This is an **approximation of the connection
aperture**, not the modeled door leaf — but it is a real, data-grounded measure
of how wide/tall the gaps between adjacent spaces are.

**2442 openings** detected across the set (6 maps yield 0 — the same CSG-poor
maps noted above, where spaces connect through mesh geometry our brush pass
can't see).

| | min | q1 | median | q3 |
|---|---|---|---|---|
| Opening **width** | 64 | 256 | **336** | 512 |
| Opening **height** | 64 | 240 | **279** | 504 |

```
 opening width (uu)                    opening height (uu)
   64-128 ██                            96-160  ███
  128-256 ████                         160-256  ██████
  256-320 ████████   <- mode           256-320  ███████████  <- mode
  320-512 ██████████                   320-448  ███████
    >=512 ████████████ (wide arches)     >=448  ███████████ (open arena mouths)
```

**Read:** the typical *connection* between spaces is **~256–384uu wide and
~256uu tall** — i.e. roughly **2–3 grid units wide, 2 units tall** on a 128uu
grid. The big >512uu tail is wide arches / arena mouths (a "room opens fully
onto the next room"), not a passable door — those are open transitions, not
ports. Filtering to apertures ≤ 512uu wide gives the doorway population proper:
mode **256uu wide × 256uu tall**.

### How well did doorway extraction work? (verdict)
- **Good enough to set a port spec.** The contact-aperture method gives a robust
  width/height distribution that cleanly supports a standard port size.
- **It conflates three things** the generator should keep distinct: true
  doorways (~256w), wide arches (>512w, open transitions), and accidental
  face-coincidences. The ≤512uu filter separates doorways from arches well.
- **It misses mesh-bounded openings entirely** (the 6 CSG-poor maps). To recover
  those would need static-mesh collision-bound decoding — see "parser work" below.

---

## RECOMMENDED MODULE GRID UNIT

### **128uu** (revising the plan's 256uu candidate **down** to 128uu)

The 256uu candidate is too coarse. Grid-alignment of brush-face planes (fraction
of the 17,982 subtract-brush edge planes landing within 1uu of a grid line):

| grid | alignment | |
|---|---|---|
| 16uu | 0.83 | (the editor's fine grid — not a module unit) |
| 32uu | 0.71 | |
| 64uu | 0.57 | |
| **128uu** | **0.42** | ← natural module quantum |
| 256uu | 0.23 | ← plan candidate: only ~1 in 4 planes land here |
| 512uu | 0.13 | |

And the fraction of room dimensions that are clean multiples:

| | mult of 64 | mult of 128 | mult of 256 |
|---|---|---|---|
| room short side | 0.66 | 0.45 | 0.25 |
| room long side | 0.65 | 0.51 | 0.34 |
| ceiling height | 0.64 | 0.46 | 0.31 |
| opening width | 0.69 | 0.54 | 0.35 |

**Reasoning:** room/door dimensions quantize on **64uu** at the finest, but
**128uu is the largest unit that still captures ~half** of all dimensions while
keeping module sizes practical. At 256uu only a quarter of dimensions land
cleanly, so snapping modules to 256uu would distort the stock proportions
(a 256×512 room — the median — is 2×4 units at 128uu, but an awkward 1×2 at
256uu with no room for the common 384/640 sizes).

**Decision: module grid unit = 128uu**, with **256uu as the recommended default
*room cell*** (a room is typically an even number of grid units; the smallest
sensible room is 2×2 cells = 256×256uu). This keeps every stock dimension
(128, 256, 384, 512, 640…) on the grid and the dominant 256/512 sizes on
even multiples.

---

## DOORWAY PORT SPEC

A **port** is a connection point on a module's wall where another module can
snap. Standardized from the opening distribution above:

| Property | Value | Rationale |
|---|---|---|
| **Port width** | **256uu** (2 grid units) | Mode of opening widths ≤512; passes a pawn two-abreast; safe bot nav. |
| **Port height** | **256uu** (2 grid units) | Mode of opening heights; one full story; clears the ~88uu pawn + jump. |
| **Min port width** | 128uu (1 unit) | Single-file squeeze; floor of the corridor distribution. |
| **Wide/arch port** | 384–512uu (3–4 units) | Optional "grand opening" variant for arena mouths. |
| **Threshold (sill) Z** | flush with room floor (offset Z = 0) | Stock doorways open at floor level; no step. |
| **Wall alignment** | port rectangle is **centered on, and inset to, the 128uu grid**; its left/bottom edge sits on a grid line | Guarantees two abutting modules' ports coincide. |
| **Offset convention** | port position = `(grid-cell index along the wall) × 128uu` from the module's local origin (min corner of its footprint AABB), measured along the wall's tangent; Z from the floor plane | Deterministic snap: module A's port at wall-cell *k* mates module B's port at the shared wall when their footprints abut on the grid. |

### Port = a 256×256uu rectangular hole, on the grid, floor-flush, wall-centered.

Two modules connect when each exposes a port of equal (or the smaller "min")
width/height at the same grid coordinate on their shared wall plane. The
generator carves the port as a `CSG_Subtract` passage brush spanning the wall
thickness, floor-flush, 256 wide × 256 tall by default (256w×256h corridor stub
between the two rooms). Wider transitions use the 384/512 arch variant.

This satisfies the nav constraints already on record: a 256uu-wide,
floor-flush opening keeps walk-edge gaps far under the hard `walk_gap < 1200uu`
ceiling (`PARAM_SCHEMA.md`) and supports the target out-degree ≈ 4 (a room with
4 ports = 4 neighbours).

---

## Generator defaults (brush side) — drop-in for the module library

```
grid_unit:            128 uu        (HARD: all module dims are multiples of 128)
room_cell:            256 uu        (default smallest room = 2x2 cells)
room_footprint:       256 x 512 uu  (median; range 256x256 .. 896x896 typical)
ceiling_height:       256 uu        (default story); 512 uu for tall rooms
corridor_width:       256 uu        (single-file w/ clearance); 128 min, 384 wide
port_width:           256 uu        (2 grid units)
port_height:          256 uu        (2 grid units)
port_sill_z:          0  (floor-flush)
port_offset:          k * 128 uu along the wall from the module's min corner
arch_port:            384-512 uu    (optional grand-opening variant)
```

---

## What parser work would unlock more

| Gap | What's missing | Priority |
|---|---|---|
| Mesh-bounded openings | The 5–6 CSG-poor maps build walls/doors from static meshes; their collision bounds aren't decoded, so openings there are invisible to the brush pass. Decoding `StaticMesh` collision/bounds (or the `KMeshProps` already present) would let the aperture method see mesh-walled spaces. | Medium |
| True door-leaf size | Mover doors (`Mover` actors with brush models) carry their own geometry; surveying *Mover* brush bboxes would give the actual door-leaf dimensions (vs. our contact-aperture proxy). The parser already decodes Mover brushes — a follow-up pass over `Mover` CsgOper/Brush would add this directly. | Medium |
| Room adjacency graph | The contact-aperture pass already computes which subtract volumes touch — promoting that to a persisted room-adjacency graph (which room connects to which, via which port) would feed the module-assembler's room-graph directly. | Low |
| Per-room labelling | We measure volumes, not named rooms; clustering adjacent subtracts into "rooms" (vs. corridor segments) would sharpen the footprint distribution. | Low |
```
