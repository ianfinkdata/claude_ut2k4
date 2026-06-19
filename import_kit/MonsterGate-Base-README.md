# MonsterGate-Base.t3d — source-of-truth base build (monster-gate component)

**This is the canonical base build for the "monster-gate room" procedural
component.** Treat it as the source of truth: changes to the monster-gate module
start here.

## Lineage

```
import_kit/MonsterGate-Spike.t3d   (generated)
        │  pasted + built + hand-finished in UnrealEd by the user
        ▼
Maps/claude_test_monster_spike.ut2 (committed to main — funtested, v128)
        │  ut2parser --t3d --t3d-saveable   (strips ReachSpec/StaticMeshInstance/
        │                                    built Models — engine regenerates them)
        ▼
        │  apply_palette.py + palettes/tech-rankin.json   (re-skin by face role)
        ▼
import_kit/MonsterGate-Base.t3d    (THIS FILE)
```

The geometry + gameplay wiring here is **human-funtested** (it ran in-engine: the
WarLords spawn and fight, the static-mesh door imported, paths built — 92
ReachSpecs in the committed map). The only programmatic change from the committed
map is the **texture re-skin**: the placeholder `UCGeneric` surfaces were replaced
with the `tech-rankin` palette (`HumanoidArchitecture` — the DM-Rankin look).

## Contents (45 actors)

- 3 × `WarLord` guardians wired to a `Counter` (`Event="MonsterKill"`).
- 1 × `Counter` (`NumToCount=3`) → triggers the door.
- 1 × `Mover` door (static-mesh, `CP_UT2K3_TechSetMesh1` door).
- 3 × `xWeaponBase` chargers (Redeemer reward + Rocket/Flak arena weapons).
- Combat loadout: `RocketAmmoPickup`, `FlakAmmoPickup`, 2 × `MiniHealthPack`,
  `ShieldPack`.
- 8 × `InventorySpot` (1:1 with pickups), 4 × `PlayerStart`, PathNodes, Lights.

Surfaces: 16 wall polys → `HumanoidArchitecture.Bases.bas02HAb`; 8 floor/ceiling
polys → `HumanoidArchitecture.Floors.flr03HA`.

## Regenerate

```bash
# 1. pull the funtested map from main and export a saveable T3D
git show origin/main:Maps/claude_test_monster_spike.ut2 > spike.ut2
python ut2parser.py spike.ut2 --t3d --t3d-saveable > base_raw.t3d
# 2. re-skin with the tech palette
python apply_palette.py base_raw.t3d palettes/tech-rankin.json -o import_kit/MonsterGate-Base.t3d
```

Swap `palettes/tech-rankin.json` for another palette to re-theme the same module.

## Use

Paste into a blank UnrealEd level → Build Geometry → Build Lighting → Build AI
Paths (regenerates the stripped ReachSpecs) → Play. See `manual_instructions.md`.
`HumanoidArchitecture.utx` and `CP_UT2K3_TechSetMesh1.usx` must be present (they
are in a stock UT2004 install).
