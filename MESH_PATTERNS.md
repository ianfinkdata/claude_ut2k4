# UT2004 DM — Static-Mesh Placement Patterns

Mined from all 39 stock Deathmatch maps with `surveys/mesh_survey.py` (built on
`ut2parser`). These are the **repeatable rules** behind how the stock maps dress
their rooms with `StaticMesh` actors — the raw material for a procedural
generator's "dress the module" pass. Theme focus: **tech / industrial**, which is
the dominant stock-map look.

Run it yourself: `python surveys/mesh_survey.py Maps/DM-*.ut2`  (add `--json` for
the per-map data in `surveys/meshes.json`).

---

## Static meshes in one paragraph

A placed mesh is a **`StaticMeshActor`** carrying a `StaticMesh` object reference
(`StaticMesh'Pkg.Group.Name'`), a `Location`, usually a `Rotation`, and optionally
`DrawScale` (scalar) / `DrawScale3D` (per-axis vector). The reference's middle
segment — the asset **Group** (`Beams`, `Walls`, `Lights`, `Pipes`,
`Miscellaneous`, …) — is the single most reliable role signal: mappers organize a
mesh package's content into groups by function. A few other actor classes also
carry a `StaticMesh` (`xWeaponBase`, `HealthCharger`, `Mover`, `KActor`,
`MeshEmitter`) but `StaticMeshActor` is ~97% of all placements. The mesh geometry
itself is a separate, public asset package shipped with the game; the map only
stores the *reference* plus the transform — so the generator's job is choosing a
mesh + transform, not authoring geometry.

---

## Cross-map invariants (39 maps, 24,582 mesh placements)

| Metric | Value | Reading |
|---|---|---|
| avg mesh actors / map | **630** | a stock DM map is ~630 placed meshes |
| avg distinct meshes / map | **~51** | built from a *small palette* re-placed heavily (≈12× reuse) |
| **yaw snapped to 90°** | **median 100%** per mesh | **axis-aligned placement is the rule** — meshes snap to the 16384-uu (90°) grid |
| **non-uniform `DrawScale3D`** | median **0%** per mesh | most meshes placed at authored size; stretching is the exception, used deliberately on runs (beams/walls) |
| unresolved mesh refs | **0** across all maps | parser resolves every placed mesh ref |
| charger meshes (`2k4ChargerMeshes`) | in **37 / 39** maps | weapon/health pickup bases are near-universal |

### Global role mix (the dressing budget)

| Role | % of placements | |
|---|---|---|
| structural (pillars, beams, braces, girders) | **20%** | |
| pipe / duct / conduit / cable | **19%** | the tech-industrial signature |
| light (lamps, spotlights, light tubes) | **10%** | |
| wall (panels, bulkheads) | **8%** | |
| trim (edges, corners, molding) | **7%** | |
| deco / misc (chains, detail props) | **4%** | |
| floor (grates, catwalks, planks, decks) | **3%** | |
| nature / machine / debris / container | ~2% each | |
| ceiling / door / window / rail / sky | ≤1% each | |
| *other* (uncategorized, incl. pickup bases) | 14% | |

### Collapsed to the 3 generator buckets

| Bucket | % | What it is |
|---|---|---|
| **trim** (surface dressing: trim/wall/ceiling/window/rail/light/pipe-deco) | **48%** | half of every map is surface detail laid *along* brush faces |
| **prop** (freestanding objects in the room volume) | **26%** | |
| **structural** (load-bearing / room-defining: pillar/beam/door/floor) | **24%** | |

> The headline rule: **~half of all mesh placement is trim** — edge/surface
> dressing snapped along walls, ceilings and beams — split roughly evenly between
> the remaining quarter structural and quarter freestanding props.

---

## Recommended TECH mesh palette

These are the stock tech/industrial mesh packages, ranked by total placements and
map coverage. They are **public game assets** (resolvable by qualified reference),
and they **co-occur** — the generator can safely mix them in one map, because the
stock maps do exactly that (see co-occurrence below).

| Package | Placements | In #maps | Strongest roles | Anchor meshes (`Group.Name`) |
|---|---|---|---|---|
| **ShiptechHardware** | 2,391 | 12 | pipe, wall, structural, trim | `Miscellaneous.DPipe2aCS`, `Miscellaneous.DPipe4gCS`, `Miscellaneous.Trim01CS`, `WallPanels.Hall03CS` |
| **HumanoidHardware** | 2,284 | 15 | structural, pipe, deco, wall, floor | `Beams.jgirder01HA`, `Miscellaneous.SCductworkstraight01HA`, `Miscellaneous.MChain01HA`, `Beams.jribbedcolumn01HA` |
| **AbaddonHardware** | 1,676 | 11 | structural, light, wall, pipe | `Beams.Support01AB`, `Beams.SupTopBeam01BA`, `Lights.Alight01AB` |
| **Pipe_Static** | 1,342 | 15 | pipe, light | `General.TubeTubeLightA`, `General.TubeCeilingB`, `General.TubeFenceCeiling` |
| **AlleriaHardware** | 875 | 14 | light, pipe, floor | `Lights.Light01AB`, `Pipes.ALgPipe04AL`, `Lights.light02AL` |
| **2k4ChargerMeshes** | 443 | **37** | pickup bases | `ChargerMeshes.WeaponChargerMesh-DS`, `ChargerMeshes.HealthChargerMESH-DS` |
| **cp_Mechstaticpack1** | 638 | 6 | light, structural, machine, door | `Braces.cp_lp_Mechsupport2`, `Braces.cp_lp_Mechbrace1`, `Doors.cp_lp_Mechdoorway1`, `Lights.cp_lp_Mechlight4` |
| **SG_LO_meshes** | 1,201 | 4 | machine, structural, pipe, ceiling, light | `Deco1.sg_Mech_ruggedS`, `Deco1.sg_Mech_pipe8`, `Cielings.sg_Mech_gdrstrut` |

> **Default tech kit (highest coverage, mixes cleanly):**
> `ShiptechHardware` + `HumanoidHardware` + `AbaddonHardware` + `AlleriaHardware`
> + `Pipe_Static`, with `2k4ChargerMeshes` for pickup bases. The `cp_Mechstaticpack1`
> and `SG_LO_meshes` (`sg_Mech…`) packs are the heavier "mech bay" look — use them
> when a room module wants machinery as props.

### Package co-occurrence (which kits ship together — used in N maps)

```
15  2k4ChargerMeshes + HumanoidHardware
15  2k4ChargerMeshes + Pipe_Static
14  2k4ChargerMeshes + AlleriaHardware
12  2k4ChargerMeshes + ShiptechHardware
11  2k4ChargerMeshes + AbaddonHardware
10  AbaddonHardware  + HumanoidHardware
10  HumanoidHardware + Pipe_Static
10  Pipe_Static      + ShiptechHardware
 9  HumanoidHardware + ShiptechHardware
 9  AlleriaHardware  + HumanoidHardware
```

`2k4ChargerMeshes` co-occurs with everything (it's the pickup-base pack). Among the
architecture packs, `HumanoidHardware`, `Pipe_Static`, `AbaddonHardware`,
`ShiptechHardware` and `AlleriaHardware` form a tightly-knit cluster — they are the
canonical UT2004 tech-set and look consistent together.

---

## Placement rules by role (for per-module dressing)

The generator should pick a mesh from the palette by **role**, then place it with
the transform conventions below. Roles map to the 3 buckets; a room module declares
how much of each it wants.

### Universal transform conventions
- **Yaw snaps to 90°** (16384 uu). Place meshes axis-aligned to the room grid
  unless a deliberate diagonal accent is wanted (median per mesh: 100% snapped).
- **Default scale by default.** Leave `DrawScale3D = (1,1,1)` for most placements.
  Use non-uniform scale only to *fit a run to a span* (see structural/trim below).
- **Pitch/roll are rare** — meshes lie flat on their authored orientation; tilting
  is reserved for ramps, debris and the occasional angled pipe.

### Bucket = trim (~48%) — dress the surfaces
*Roles: trim, wall, ceiling, window, rail, light, pipe-deco.* These hug a brush
face. They are placed **along** walls/ceilings, flush to the surface, and are the
most-reused meshes (a single wall panel or pipe can appear 50–120× in one map).
- **Wall panels** (`ShiptechHardware.WallPanels.*`, `HumanoidHardware.WallPanels.*`):
  tile along wall faces; frequently stretched non-uniformly (X/Z) to span the wall
  segment exactly. Yaw = the wall's facing.
- **Pipes / ducts / conduit** (`ShiptechHardware.Miscellaneous.DPipe*`,
  `Pipe_Static.General.*`, `…Pipes.*`): run **along** wall/ceiling edges; often
  scaled on one axis to set length. Pipes are *the* tech-industrial tell (19% of
  all meshes) — generously route them along ceiling corners and wall bases.
- **Lights** (`AbaddonHardware.Lights.*`, `AlleriaHardware.Lights.*`,
  `Pipe_Static.General.Tube*Light*`): on walls and ceilings, near-uniform scale,
  yaw-snapped. Pair with the map's actual light actors.
- **Trim / edge caps** (`…Trim01CS`, `skyline-*-edger`): along the meeting line of
  two surfaces; minimal scaling.

### Bucket = structural (~24%) — define the room shell
*Roles: structural (pillar/beam/brace/girder), door, floor.* Load-bearing-looking,
placed at junctions and spans; they read as part of the architecture.
- **Beams / girders / braces** (`AbaddonHardware.Beams.Support01AB`,
  `HumanoidHardware.Beams.jgirder01HA`, `cp_Mechstaticpack1.Braces.*`): span
  ceilings and corners; **stretch one axis** to bridge the gap (the main legitimate
  use of non-uniform `DrawScale3D`). Yaw-snapped to the span direction.
- **Pillars / columns** (`…pillar…`, `…column…`, `jribbedcolumn01HA`): freestanding
  vertical, floor-to-ceiling, near-uniform scale, at room corners / mid-span.
- **Doorways / frames** (`cp_Mechstaticpack1.Doors.cp_lp_Mechdoorway1`): framing a
  brush opening; uniform scale, yaw = the opening's facing.
- **Floor pieces** (grates/catwalks/planks): laid flat over walkable brush; may be
  scaled to tile an area.

### Bucket = prop (~26%) — populate the volume
*Roles: machine, container, debris, deco, nature.* Freestanding objects sitting on
the floor in the room volume (not flush to a wall).
- **Machinery** (`SG_LO_meshes.Deco1.sg_Mech_*`, `cp_…Mechtech*`): the "this room
  has equipment in it" props — placed against a wall or in a corner, uniform scale.
- **Deco / chains** (`HumanoidHardware.Miscellaneous.MChain01HA`): hanging or
  surface detail; high reuse, low footprint.
- **Pickup bases** (`2k4ChargerMeshes.ChargerMeshes.WeaponChargerMesh-DS`,
  `HealthChargerMESH-DS`): placed under the corresponding pickup actor — this ties
  back to the nav survey's **1 pickup ⇒ 1 InventorySpot** rule; the charger mesh is
  the visible base of that pickup.
- **Debris / containers** (barrels, crates, scrap): scattered low props, sometimes
  tilted (pitch/roll) for a "dropped" look.

### Suggested per-room mesh budget (from the global mix)
For a generated tech room, target roughly: **~half trim** (wall panels + pipes +
lights along the surfaces), **~quarter structural** (beams/pillars/doorframes
defining the shell), **~quarter props** (machinery, deco, pickup bases in the
volume). Pull all meshes from one co-occurring palette cluster for visual
consistency.

---

## Parser gaps & caveats

- **Map-local re-exports lose their source package.** Several maps (DM-Rankin
  `houre*`, DM-Corrugation `StaticMesh0…`, the DM-1on1 “Desp/Disp” packs) import
  meshes *into the map package*, so the qualified ref reads `MapName.MeshName` with
  the original source package erased and **no Group segment** to read a role from.
  These show up as `local: true` in `meshes.json`. For these, role is derived from
  the mesh name + scale signature only, which is less reliable when the name is
  opaque (`StaticMesh0`, `FConT1`). DM-Rankin's `houre*` names *are* descriptive
  (Dutch: `pillar`, `wandeel`=wall, `lamp`, `plank`) and classify well; the
  numbered ones fall into `other`. This is the main accuracy limit, not a crash —
  all refs still resolve (0 unresolved).
- **`other` role (14%)** is mostly (a) pickup-base charger meshes (correctly a
  prop, just no descriptive keyword) and (b) opaquely-named local re-exports.
  Extending `_ROLE_KEYWORDS`, or building a name→role lookup from the well-named
  packages and applying it to numbered locals, would shrink this.
- **Role is heuristic.** It comes from Group/name keywords + a scale fallback, not
  from inspecting the mesh geometry or its position relative to brush faces. The
  wall-vs-trim and structural-vs-prop split is good enough for budgeting but isn't a
  geometric ground truth. A future pass could correlate a mesh's `Location` against
  the BSP/brush polys (which `ut2parser` can decode) to confirm "flush to a wall"
  vs "freestanding".
- **No parser bug found.** `ut2parser` resolved every mesh ref, scale and rotation
  cleanly across all 39 maps; `ut2parser.py` was not modified.

See `surveys/mesh_survey.py` for the metrics and `surveys/meshes.json` for the
per-map / per-mesh data behind every number here.
