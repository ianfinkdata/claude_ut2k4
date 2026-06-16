# Manual Pipeline Instructions

Step-by-step guide for running the full code → T3D → UnrealEd → `.ut2`
pipeline by hand, for testing and validation. Use this until a Python
automation wrapper exists (see issue #11).

---

## Prerequisites

- UT2004 installed at `C:\UT2004\` (or adjust paths below accordingly).
- UnrealEd accessible at `C:\UT2004\System\UnrealEd.exe`.
- Python 3.8+ installed (for `gen_testmap.py`).
- This repo cloned locally.

---

## Step 1 — Generate the T3D

From the repo root, run:

```sh
python3 gen_testmap.py -o import_kit/TestMap-Skeleton.t3d
```

To customise room size:
```sh
python3 gen_testmap.py --room-xy 1024 --room-h 512 -o import_kit/TestMap-Skeleton.t3d
```

To generate the minimal diagnostic variant (no pickups/weapon — useful for
isolating paste issues):
```sh
python3 gen_testmap.py --minimal -o import_kit/TestMap-Skeleton-Minimal.t3d
```

**Expected output:** A plain-text `.t3d` file beginning with `Begin Map` and
ending with `End Map`. Open it in a text editor and verify:
- Line 1: `Begin Map`
- Last non-blank line: `End Map`
- `grep "Begin Actor"` → 23 lines (full) or 15 lines (minimal)

---

## Step 2 — Open UnrealEd on a blank level

1. Launch `C:\UT2004\System\UnrealEd.exe`.
2. If any level is already open, go to **File → New** to start with a blank
   `Untitled` level. Do **not** paste into an existing level.
3. Verify the 3D viewport is visible and redraws without error (the viewport
   should show an empty grey void).

> **Troubleshooting:** If UnrealEd crashes immediately on launch or on viewport
> redraw with a GPF (`USkeletalMeshInstance::Render`), see
> `import_kit/TestMap-Skeleton-README.md` → "Resolved issue" section.

---

## Step 3 — Paste the T3D

1. Open `import_kit/TestMap-Skeleton.t3d` in any text editor (Notepad works).
2. **Select all** (Ctrl+A) and **Copy** (Ctrl+C).
3. Switch to UnrealEd.
4. **Edit → Paste** (Ctrl+V) — or use the toolbar paste button.

**Expected log output** (bottom-left UnrealEd log pane):
```
Pasting from clipboard...
   Pasted 23 actors
```

No red error lines. If you see `Object not found: ...` warnings, the T3D
references an external asset that's missing — check the actor class name and
verify the corresponding `.u` or `.usx` package is in `UT2004/System/`.

> The current `TestMap-Skeleton.t3d` is self-contained and references only
> built-in classes; no warnings are expected.

---

## Step 4 — Build Geometry

**Build → Build Geometry** (or **Build → Build All** and let it run all steps
in sequence — see note below).

What happens:
- UnrealEd processes the two `Brush` actors (`RoomShell` CSG_Subtract,
  `CenterPlatform` CSG_Add) in CSG order and rebuilds the level `Model`.
- The 3D viewport should update to show a hollow room with a small raised
  platform in the centre.

**Expected log output:**
```
Building geometry...
   Merging polygons...
   Build BSP...
   Build complete.
```

**Verify:** In the 3D viewport (perspective view), you should be able to see
inside the room — walls, floor, ceiling — and a 256×256×64uu box platform in
the centre. If the viewport still shows a grey void (no room), Build Geometry
did not complete correctly.

> **Build All shortcut:** **Build → Build All** runs Geometry + Lighting +
> Paths in one shot. This is fine for validation; just allow each step to
> complete before closing UnrealEd.

---

## Step 5 — Build Lighting

**Build → Build Lighting** (skip if you used Build All in step 4).

What happens:
- UnrealEd bakes the 5 `Light` actors onto the BSP surfaces.
- The 3D viewport updates from fullbright (default) to baked lighting.

**Expected log output:**
```
Building lighting...
   ...
   Build complete.
```

**Verify:** The room should be lit (not uniformly flat/fullbright) with
visible shadows and brighter areas near each light position.

---

## Step 6 — Build Paths (AI Paths)

**Build → Build AI Paths** (or included in Build All).

What happens:
- UnrealEd generates `ReachSpec` edges connecting `PathNode`, `InventorySpot`,
  and `PlayerStart` nodes based on line-of-sight and collision.
- Per `NAV_PATTERNS.md`, expect ~4 reachspecs per node (all walk edges for
  this flat single-room layout).

**Expected log output:**
```
Building paths...
   Pruning paths...
   Build complete.
```

**Verify:** Open **Tools → Path Builder** (or look for the path-display toggle
in the toolbar) to render path edges in the 3D viewport. You should see a
connected graph covering all 4 `PlayerStart`s, 4 `PathNode`s, and 4
`InventorySpot`s with no isolated/orphaned nodes.

> If `Pruning paths: X paths removed` shows a large number (>20% of nodes),
> some nodes may be placed in geometry or too far apart. Check the skeleton
> generator's PathNode positions vs. the room size.

---

## Step 7 — Verify pickups in the viewport

After building geometry, the 4 pickups should be visible in the 3D viewport
at their spawn locations (~16uu above the floor):

| Actor | Location (approx.) |
|---|---|
| `MiniHealthPack0` | (0, 300, 16) — north of platform |
| `ShockAmmoPickup0` | (0, -300, 16) — south |
| `AdrenalinePickup0` | (-300, 0, 16) — west |
| `xWeaponBase0` | (300, 0, 16) — east |

If a pickup appears embedded in the floor or floating oddly, check its Z
position in the generator (`gen_testmap.py` `build_map()`).

---

## Step 8 — Save As `.ut2`

**File → Save As** (not Save — a new level has no path yet).

Rules for the save path (from PROGRESS.md Step 7):
- Save directly into `C:\UT2004\Maps\` — e.g. `C:\UT2004\Maps\DM-TestSkeleton.ut2`
- Filename must start with `DM-` for the game to list it in the DM map picker.
- Keep the full path **under ~64 characters** to avoid a known UnrealEd
  save-path bug.

**Expected:** UnrealEd log shows `Saving package: DM-TestSkeleton`. No errors.

---

## Step 9 — Validate in UT2004

### Quick in-editor play

**View → Play This Level** (or the green Play button in the toolbar). UT2004
launches in the editor and drops you into the map. Verify:
- You can move around the room.
- The platform is solid (you can jump onto it).
- Pickups are visible and collectible.

Press Escape / close the play window to return to UnrealEd.

### Bot validation

From the UT2004 main menu:
1. **Instant Action → Deathmatch**
2. Select `DM-TestSkeleton` from the map list.
3. Add 2 bots (minimum, per issue #9 MVM criteria).
4. Start the match.

**Check:**
- Bots spawn at the `PlayerStart` corners.
- Bots navigate around the room and platform (not stuck in place).
- Bots pick up items (health/ammo/adrenaline/weapon).

### `ucc analyzecontent` validation

From a command prompt:
```bat
cd C:\UT2004\System
UCC.exe analyzecontent DM-TestSkeleton.ut2
```

**Expected output:** 0 errors, 0 critical warnings. Any `missing package` or
`broken reference` errors indicate T3D actor references that didn't resolve
on save.

---

## Step 10 — Verification checklist

Copy this checklist into the test session notes:

- [ ] T3D generated cleanly (`Begin Map` … `End Map`, correct actor count)
- [ ] UnrealEd opened on blank `Untitled` level
- [ ] **Paste**: 23 actors logged, no error lines
- [ ] **Build Geometry**: room hollow, platform solid, visible in 3D viewport
- [ ] **Build Lighting**: room lit (not fullbright)
- [ ] **Build Paths**: connected graph, no orphaned nodes, no large prune count
- [ ] **Pickups**: all 4 visible at correct positions (~16uu above floor)
- [ ] **Save As**: saved to `C:\UT2004\Maps\DM-TestSkeleton.ut2` without error
- [ ] **Play This Level**: player can move around and access pickups
- [ ] **Bot match**: 2+ bots navigate and pick up items
- [ ] **ucc analyzecontent**: 0 errors

---

## Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| GPF on paste (`USkeletalMeshInstance::Render`) | Bare `Weapon` subclass in T3D | Use `xWeaponBase` charger instead (see `TestMap-Skeleton-README.md`) |
| "Object not found" on paste | Missing package reference | Verify actor class names match installed packages |
| Room not visible after Build Geometry | CSG order wrong / brush outside world | Check brush `Location` and `CsgOper` in T3D |
| Fullbright after Build Lighting | No `Light` actors pasted | Check light count in paste log |
| Bots stuck / not navigating | No path graph | Run Build AI Paths; check for orphaned nodes |
| Save fails / corrupt `.ut2` | Path too long or non-`Maps/` directory | Save to `C:\UT2004\Maps\` with short filename |
| Not in map list in UT2004 | Missing `DM-` prefix | Rename file to start with `DM-` |

---

## Regenerating variants

```sh
# Default 1536×1536×384 room
python3 gen_testmap.py -o import_kit/TestMap-Skeleton.t3d

# Larger room
python3 gen_testmap.py --room-xy 1024 --room-h 512 -o import_kit/TestMap-Skeleton.t3d

# Minimal (no pickups — for paste-crash diagnosis)
python3 gen_testmap.py --minimal -o import_kit/TestMap-Skeleton-Minimal.t3d
```

After regenerating, repeat from Step 3 (File → New in UnrealEd first).
