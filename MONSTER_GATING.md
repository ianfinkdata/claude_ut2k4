# Monster Gating — Feasibility, Test Procedure & Schema (Agent #6)

Owner: gameplay-systems agent. Retires the **map-only monster risk** in
`PLAN_MONSTERBASE.md` and defines the **gating schema** that room modules embed
so Agent #7's generator can emit it parametrically.

Status of the in-engine confirmation: **PENDING A HUMAN RUN.** Everything below
the "Feasibility verdict" is derived from the stock UnrealScript source and the
installed packages. The actual "do monsters tick under DM?" observation is a
manual UnrealEd/UT2004 step (Section 2) — this agent cannot run UnrealEd.

---

## 0. TL;DR verdict

**Map-only monsters under plain Deathmatch are very likely to WORK — confirmed at
the source level, pending one human in-engine run.** A placed `Monster` pawn
spawns *its own* `MonsterController` and possesses itself in
`Monster.PostBeginPlay()`, with **no gametype check**. The door-gating chain
(monster `Event` on death → `Counter` → `Mover`) is all stock, code-free, and
every link is confirmed in source.

The **one real caveat** is the team-roster path that bites in *team* games
(TDM/CTF/etc.). Plain **DM (`xDeathMatch`) is not a `TeamGame`**, so it should
not apply — but this is the single thing the human run must watch for. Fallbacks
are in Section 4 if the run disproves it.

---

## 1. Feasibility findings (with sources)

### 1.1 Monsters exist locally and are placeable

`SkaarjPack.u` is installed (`C:\UT2004\System\SkaarjPack.u`). Confirmed monster
classes present in its name table:

| Class | Package | Notes |
|---|---|---|
| `Skaarj` | `SkaarjPack` | base bipedal melee/proj guardian |
| `Krall` / `Brute` / `Gasbag` | `SkaarjPack` | ranged / tanky variants |
| `Manta` / `RazorFly` (`Pupae`) | `SkaarjPack` | flyers / swarm |
| `Behemoth` / `Titan` | `SkaarjPack` | heavy |
| `IceSkaarj` / `FireSkaarj` | `SkaarjPack` | elemental Skaarj |
| **`Warlord`** | `SkaarjPack` | **the showcase guardian (flying, rockets)** |

Class hierarchy (from UnCodeX):
`Engine.Pawn → UnrealGame.UnrealPawn → XGame.xPawn → SkaarjPack.Monster → <each monster>`.
So `Monster` and its subclasses are ordinary `xPawn`s — the same family the engine
already serializes for bots. T3D actor references resolve as `Class=Skaarj`,
`Class=Warlord`, etc. (package auto-resolves because `SkaarjPack.u` is loaded).

### 1.1b Monster infighting — RULE: one species per gate (source-predicted; clean in-engine confirmation PENDING)

In-engine test: 3 guardians (Skaarj + Krall + Warlord) spawned and attacked under DM
✅ — but also attacked **each other** (expected: a mixed-species pack with <4 humans).
A follow-up all-Warlord edit was made to the spike, but a clean re-test has NOT yet
confirmed zero infighting (the contradicting observation may have used the stale
pre-edit clipboard). **Do not mark this rule confirmed until an all-one-species pack
is re-pasted and observed.** Root cause, from `MonsterController.SetEnemy()`
(exported from `SkaarjPack.u`):

```
bNewMonsterEnemy = bHateMonster
    && (Level.Game.NumPlayers < 4)     // HUMANS only — bots increment NumBots, not NumPlayers
    && !SameSpeciesAs(NewEnemy)        // different Monster class (parent/child check)
    && !NewEnemy.Controller.bIsPlayer;
```

`bHateMonster=true` is set only by **retaliation** (a monster taking damage from another
monster — `MonsterController.UC:1410`). So a monster turns on a neighbour ONLY when the
neighbour is a **different species** AND there are **< 4 human players**.

**GENERATOR RULE: each gated encounter uses a SINGLE monster species** (e.g. 5×`Warlord`).
`SameSpeciesAs()` is a class parent/child test → a same-species pack can never satisfy
`!SameSpeciesAs` → `bNewMonsterEnemy` is always false → **zero infighting, any player count,
even under friendly fire.** Subclasses count as same species (Skaarj+Fire/IceSkaarj = one
species), allowing variety within an infight-proof pack. Mixed-species packs are PROHIBITED
unless the map guarantees 4+ human players (not reliable — do not depend on it).

Nuances found in source:
- `Warlord` **overrides** `SameSpeciesAs` to count both Skaarj AND Warlord as kin
  (`P.IsA('Skaarj') || P.IsA('WarLord')`). So Warlords ignore Skaarj — but base
  `Skaarj` uses the default child-of test and does NOT treat Warlord as kin, so the
  relationship can be **asymmetric**. Safest is still literally one class per gate.
- **Gating is robust to infighting regardless:** the kill `Counter` fires on the
  monster's `Died()`/`Event`, so monster-on-monster kills still open the door (they
  just trivialise the challenge). Infighting is a difficulty/feel issue, not a
  gate-correctness issue.

### 1.2 The decisive fact: a placed Monster self-spawns its controller, gametype-independent

`SkaarjPack.Monster.PostBeginPlay()` (UnCodeX source) is unconditional:

```unrealscript
event PostBeginPlay()
{
    Super.PostBeginPlay();
    if ( (ControllerClass != None) && (Controller == None) )
        Controller = spawn(ControllerClass);   // ControllerClass = MonsterController
    if ( Controller != None )
    {
        Controller.Possess(self);
        MyAmmo = spawn(AmmunitionClass);
    }
}
```

Default property: `ControllerClass=Class'SkaarjPack.MonsterController'`. And the
generic `Engine.Pawn.PostBeginPlay()` already spawns+possesses the
`ControllerClass` for any editor-placed pawn when `Level.bStartup && Health>0 &&
!bDontPossess`. **Neither path checks the gametype.** `MonsterController extends
ScriptedController extends AIController` and has `FindNewEnemy()/SetEnemy()` — it
hunts any enemy player it finds. There is **no `if (Invasion)` gate** anywhere on
the spawn/possess/attack path.

Conclusion: the long-held belief that "monster AI is driven by the Invasion
controller" is **only half true** — Invasion drives *wave spawning* and *which*
monsters appear, but an individually placed Monster brings its own controller and
runs AI on its own. This is exactly why a map-only approach is viable.

### 1.3 The honest caveat — team games only

The documented failure mode (Beyond Unreal Wiki, OSMT tutorial) is:
> "placing UT2004 Monsters in a map designed for a **TeamGame** will result in a
> team imbalance, where `UnrealPawn.PostNetBeginPlay()` attempts (and eventually
> fails) to place the Monster in an `xTeamRoster`."

This is a **team-assignment** bug, scoped to `TeamGame` subclasses. Plain
Deathmatch (`XGame.xDeathMatch`) is **not** a `TeamGame`, so there is no
`xTeamRoster` to corrupt. The risk we must verify in-engine is therefore narrow:
that the monster's PRI/team handling under plain DM doesn't (a) make the monster
inert, (b) make it un-targetable by players, or (c) make players unable to damage
it. Source review shows no reason it would, but **only the human run confirms it.**

### 1.4 Death fires the monster's Event — the gating trigger

`Engine.Pawn.Died()` (UnCodeX source) ends with:

```unrealscript
if ( Killer != None )
    TriggerEvent(Event, self, Killer.Pawn);
else
    TriggerEvent(Event, self, None);
```

So **setting a monster pawn's `Event` property makes its death broadcast that
event** to every actor whose `Tag` matches. This is the hook the whole gate hangs
on, and it is base-`Pawn` behavior — works for every monster, every gametype.

### 1.5 Counter + Mover are stock and code-free

- **`Counter`** (`GamePlay.u`, confirmed installed). Waits until triggered
  `NumToCount` times, then triggers all actors whose `Tag` matches the Counter's
  `Event`. Properties: `NumToCount`, `bShowMessage`, `CountMessage`,
  `CompleteMessage`, `Event`, `Tag`.
- **`Mover`** (`Engine.u`). `InitialState=TriggerOpenTimed` + `bTriggerOnceOnly=True`
  latches the door open on the first (Counter) trigger; receives triggers via its `Tag`.
  **Authored as a STATIC-MESH Mover, not a brush Mover** (`DrawType=DT_StaticMesh` +
  `StaticMesh='…'`): a pure-property actor that survives T3D paste reliably, where a
  brush-Mover's inline brush model does NOT rebuild on paste (root cause of the
  first spike's "open hole" door). The spike uses
  `CP_UT2K3_TechSetMesh1.Doors.cp_ut2k3_techdoor1` (native 410×83×312uu, rotated
  Yaw 90° and `DrawScale3D=(0.5,1.0,0.85)` to over-fill the 192×256uu opening so
  there are no edge gaps; collision comes from the mesh). This is also the
  generator's door strategy — doors emit fully in T3D, no in-editor step.

### 1.6 Reward weapon

`XWeapons.Redeemer` is installed (`XWeapons.u`). Placed via the **proven
`xWeaponBase` charger pattern** already used in `gen_testmap.py` (a bare `Weapon`
subclass crashes the editor's skeletal-mesh renderer — see
`weapon_charger_actor()` docstring). So the reward is
`WeaponType=Class'XWeapons.Redeemer'` on an `xWeaponBase`.

### Sources
- Beyond Unreal Wiki / UnCodeX UnrealScript browser (ericdives mirror):
  `SkaarjPack.Monster` (PostBeginPlay, ControllerClass), `SkaarjPack.MonsterController`
  (extends ScriptedController), `Engine.Pawn` (PostBeginPlay controller spawn,
  `Died()` → `TriggerEvent(Event,...)`).
  - https://ericdives.com/UT2004-UnCodex/skaarjpack/monster.html
  - https://ericdives.com/UT2004-UnCodex/skaarjpack/monstercontroller.html
  - https://ericdives.com/UT2004-UnCodex/Source_engine/pawn.html
  - https://ericdives.com/UT2004-UnCodex/skaarjpack/brute.html
- OSMT / "A UT2004 Monster Tutorial" (the team-roster caveat, controller self-spawn):
  - https://beyondunrealwiki.github.io/pages/superape-old-skool-monsta-t.html
  - https://github.com/DarklightGames/unrealwiki/blob/master/a-ut2004-monster-tutorial.html
- Counter behaviour: https://beyondunrealwiki.github.io/pages/counter.html
- Installed packages: `C:\UT2004\System\SkaarjPack.u`, `GamePlay.u`, `XWeapons.u`
  (verified by name-table scan).

---

## 2. In-engine test procedure (HUMAN STEP — confirms the verdict)

Aligns with `manual_instructions.md`. The artifact is
**`import_kit/MonsterGate-Spike.t3d`** (43 actors): a 2048×1024×512 room split by
a wall with a doorway; the doorway filled by a **static-mesh `Mover` door**; **3
`Warlord` guardians** (single species — see §1.1b) on the arena side wired to a
`Counter`; the `Counter` wired to the door; a `Redeemer` charger in the sealed
vault behind it; an **arena combat loadout** (RocketLauncher + FlakCannon chargers,
rocket/flak ammo, 2 health, a ShieldPack — each with its 1:1 InventorySpot) so the
fight is winnable; plus PlayerStarts/PathNodes for playability.

### Setup
1. `UnrealEd.exe` → **File → New** (blank `Untitled` level).
2. Open `import_kit/MonsterGate-Spike.t3d`, Select-All, Copy.
3. UnrealEd **Edit → Paste**. **Expect: `Pasted 43 actors`, no red errors.**
   - If you see `Object not found: Skaarj` etc., `SkaarjPack.u` isn't loading —
     add `EditPackages=SkaarjPack` is not needed for placement, but confirm the
     package exists in `System\`. (It does on this machine.)

### Build
4. **Build → Build All** (Geometry → Lighting → Paths). Verify:
   - Two rooms separated by a wall; the door brush fills the doorway (closed).
   - Room is lit; path graph connects arena↔doorway↔vault with no orphans.

### Save & the CRITICAL monster checks
5. **File → Save As** → `C:\UT2004\Maps\DM-MonsterGate.ut2` (short path, `DM-` prefix).
6. **Re-open the saved `.ut2`** in UnrealEd and re-parse / inspect the actor
   browser. **CHECK #1 (serialization):** are the 3 monster actors still present?
   - Per `PLAN_MONSTERBASE.md`, the prior playtest skeleton saved with **zero**
     monster pawns ("DM has nothing to own them, so they did not serialize"). If
     the monsters vanish again here, that is the **first failure signal** — note
     it and jump to Section 4 fallbacks.
7. **Instant Action → Deathmatch → `DM-MonsterGate`**, 0–1 bots, start the match.
   Observe, in order:
   - **CHECK #2 (tick/AI):** do the 3 monsters animate, notice you, and attack?
     (Stand in the arena.) If they stand frozen / never aggro, AI is not running
     under DM → Section 4.
   - **CHECK #3 (damage):** can you damage and kill them with a weapon?
   - **CHECK #4 (gate):** after killing all 3, does the `Counter`'s
     `CompleteMessage` ("The vault is breached!") fire and the **Mover door open**?
   - **CHECK #5 (reward):** can you walk into the vault and pick up the Redeemer?
8. **`ucc analyzecontent DM-MonsterGate.ut2`** → expect 0 errors / 0 critical
   warnings (no broken references).

### Pass criteria
All of CHECK #1–#5 pass → **map-only monster gating is CONFIRMED**; promote the
schema (Section 3) into the module library for Agent #7. Any check fails → record
which one and consult Section 4.

> Note on the Mover: of all the actors here, the brush-based `Mover` is the
> **least-certain to import cleanly** via raw T3D paste (movers are normally
> built from a MyLevel brush in-editor). If the door geometry imports wrong but
> monsters+Counter work, that's a *door-authoring* problem, not a *feasibility*
> problem — the monster verdict (CHECK #1–#3) still stands. A fallback door is to
> hand-convert the `VaultDoor` brush to a Mover in-editor (select brush → Actor →
> Add Mover) and re-apply the `Tag`/`KeyPos`/`InitialState` props.

---

## 3. Gating schema (for Agent #7's generator)

A **gate** is a parametric cluster of placed actors. Room modules declare gates in
their gameplay manifest; the generator emits the actors below with unique names.

### 3.1 The three roles

```
                 Event="<killTag>"            Tag="<killTag>"
   [Monster]×N  ───────────────────▶  [Counter NumToCount=N]
                                              │ Event="<doorTag>"
                                              ▼
                                       Tag="<doorTag>"
                                          [Mover door]   ──opens──▶  [xWeaponBase reward]
```

### 3.2 Manifest fields (per gate)

| Field | Meaning | Example |
|---|---|---|
| `gate_id` | unique slug; namespaces all tags/actor names | `redeemer_vault` |
| `monsters` | list of `{class, count, location, yaw}` | `[{class:Warlord, count:5}]` |
| `kill_tag` | event the monsters fire on death = Counter `Tag` | `redeemer_vault_kill` |
| `num_to_count` | = total monster count (sum of `count`) | `5` |
| `door_tag` | Counter `Event` = Mover `Tag` | `redeemer_vault_door` |
| `door` | `{location, half_extents, open_dz, move_time}` | open_dz ≥ door height + 8 |
| `reward` | `{weapon_class, location}` via `xWeaponBase` charger | `XWeapons.Redeemer` |

### 3.3 Emitted actors (T3D property recipe)

**Monster slot** (repeat per monster; all share one `kill_tag`):
```
Begin Actor Class=<MonsterClass> Name=<gate>_Mon<i>
    Event="<kill_tag>"          // ← death fires this; counted by the Counter
    Tag="<MonsterClass>"
    Location=(...)              // arena side; Warlord etc. float, Z≈+48..80
    Rotation=(Yaw=...)          // optional, face the players
End Actor
```
Leave `Health`, `ControllerClass`, `bDontPossess` at class defaults — the monster
self-spawns its `MonsterController` (Section 1.2). Do **not** set a team.

**Counter** (one per gate):
```
Begin Actor Class=Counter Name=<gate>_Counter
    NumToCount=<N>              // = total monsters in this gate
    bShowMessage=True
    CountMessage="..."          // optional flavour, "%i" = remaining
    CompleteMessage="..."       // optional
    Event="<door_tag>"          // ← what it triggers at zero
    Tag="<kill_tag>"            // ← what the monsters' Event points at
    Location=(...)
End Actor
```

**Mover door** (one per gate; brush-based, same polygon template as room brushes):
```
Begin Actor Class=Mover Name=<gate>_Door
    InitialState=TriggerOpenTimed
    bTriggerOnceOnly=True
    MoverEncroachType=ME_IgnoreWhenEncroach
    MoverGlideType=MV_GlideByTime
    MoveTime=2.0
    StayOpenTime=10000.0        // effectively "stay open"
    NumKeys=2
    KeyPos(0)=()                // closed (origin)
    KeyPos(1)=(Z=<open_dz>)     // open: slide up out of the doorway
    Tag="<door_tag>"            // ← receives the Counter's Event
    Location=(...)
    Begin Brush Name=Model<gate>Door ... (box_faces template) ... End Brush
    Brush=Model'MyLevel.Model<gate>Door'
End Actor
```

**Reward** (one per gate; reuse `weapon_charger_actor()` + `inventory_spot_actor()`):
```
Begin Actor Class=xWeaponBase Name=<gate>_Reward
    WeaponType=Class'<weapon_class>'    // e.g. XWeapons.Redeemer
    myMarker=InventorySpot'MyLevel.<gate>_RewardSpot'
    StaticMesh=StaticMesh'2k4ChargerMeshes.ChargerMeshes.WeaponChargerMesh-DS'
    Tag="xWeaponBase"
    Location=(...)              // behind the door (vault side)
    PrePivot=(Z=3.7)
End Actor
Begin Actor Class=InventorySpot Name=<gate>_RewardSpot
    myPickupBase=xWeaponBase'MyLevel.<gate>_Reward'
    Location=(...)              // floor-snapped below the reward (1:1 anchoring, NAV_PATTERNS.md)
End Actor
```

### 3.4 Module-embedding rules

- **Tag namespacing:** prefix every `kill_tag`/`door_tag`/actor `Name` with
  `gate_id` so multiple gates in one map never cross-trigger.
- **`NumToCount` must equal the monster count** in the gate, or the door never
  opens (under-count) / opens early (over-count, e.g. if a monster suicides).
- **Reward lives behind the door** (the "vault"); the door's closed brush must
  fully seal the only walkable port into the vault, or players bypass the gate.
- **Nav:** drop a `PathNode` in the doorway threshold and ≥1 in the vault so bots
  path through once the door opens; keep walk gaps < 1200uu (NAV_PATTERNS.md). The
  ReachSpec through a Mover doorway gets `reachFlags door=16` after Build Paths.
- **Monster placement:** arena side only, off the floor for flyers (Warlord/Manta
  Z≈+48..80); keep them outside the door's swept volume so the opening door can't
  crush/block them (we use `ME_IgnoreWhenEncroach` as belt-and-braces).

### 3.5 Generator hook

`gen_testmap.py` already exposes `brush_actor`, `box_faces`, `light_actor`,
`weapon_charger_actor`, `inventory_spot_actor`. Agent #7 adds three emitters —
`monster_actor()`, `counter_actor()`, `mover_door_actor()` — matching 3.3, and a
`emit_gate(manifest)` that stamps a full gate from a manifest dict. The spike
generator code that produced `MonsterGate-Spike.t3d` is the reference
implementation for these (see that file's actor set).

---

## 4. Fallbacks (only if the human run FAILS a check)

Escalate to the user with the failing check number; do **not** silently switch
paths (per `PLAN_MONSTERBASE.md`). Smallest-first:

1. **Monsters vanish on save (CHECK #1 fails):** the package didn't keep the
   pawns. Try setting `bStatic=False`/`bNoDelete=True` explicitly, and confirm
   `SkaarjPack` is loaded. If they still don't serialize under DM, this is the
   hard blocker → option 3 or 4.
2. **Monsters present but inert / un-damageable (CHECK #2/#3 fail):** likely the
   team/PRI handling. Cheapest fix is a **one-line mutator** whose only job is, in
   `ModifyPlayer`/`PostBeginPlay`, to (re)possess placed monsters or clear a bad
   team — far smaller than a full scripted system. Still "mostly map," one tiny
   `.u`.
3. **Build on the Invasion gametype** instead of DM: monsters are first-class
   there (waves, controller, scoring) — but it changes the game feel from "DM in a
   monster base" to "co-op survival," and wave spawning isn't the placed-guardian
   model. A design pivot, flag to user.
4. **Minimal mutator for the whole concept:** a small `MonsterDM` mutator that
   spawns/owns placed guardians and handles the gate counters in code. Most robust,
   but breaks the "map-only, no UnrealScript" locked decision — user call.

Door-only failure (Mover imports wrong but monsters work) is **not** a
feasibility failure — hand-convert the door brush to a Mover in-editor (Section 2
note) and keep the map-only verdict.
