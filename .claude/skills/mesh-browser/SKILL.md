---
name: mesh-browser
description: >-
  Browse the static-mesh usage data mined from the 39 stock UT2004 DM maps
  (surveys/meshes.json). For any mesh it surfaces the mesh PACKAGE, the mesh NAME
  (and group), its role/bucket, a scale hint, and EXAMPLE MAPS that use it, ranked
  by placement count. Use this whenever the user wants to find, look up, compare,
  or pick a UT2004 static mesh — e.g. "find a door mesh I can use as a mover",
  "what pipe meshes do stock maps use?", "which package has good tech trim?",
  "show me machinery props", "what mesh is cp_ut2k3_techdoor1 and where's it
  used?", or any time you're choosing meshes for procedural map generation.
  Trigger it even when the user just describes a prop (crate, beam, light fixture,
  doorway, railing) without naming a mesh.
---

# Mesh Browser

Browse how the stock UT2004 Deathmatch maps actually place static meshes, so mesh
choices are grounded in shipped maps. Data comes from `surveys/meshes.json`
(produced by `surveys/mesh_survey.py`): per map, every `StaticMesh`-bearing actor,
with placement counts, a fine role + coarse bucket, source package, and scale
stats.

## When to use

Reach for this whenever the user is **finding, comparing, or choosing a static
mesh** — by keyword, package, or role (door, pipe, trim, machine, light, …). It's
the go-to for "what mesh fits this job, and which stock maps prove it." Especially
useful for finding a **door mesh to drive with a Mover**, trim to dress a wall, or
props to populate a room in the procedural generator.

## How to run

stdlib-only Python; auto-locates `surveys/meshes.json` (override with `--data`).

```bash
python .claude/skills/mesh-browser/scripts/query.py <term> [options]
```

Each result shows the **package**, **name** (and group), **role/bucket**, a
**scale hint** (typical DrawScale + how often it's stretched), and the **example
maps** that use it (most placements first, count in parentheses).

### Common patterns

**Find a door** (the role you'll want for a Mover door):
```bash
python .claude/skills/mesh-browser/scripts/query.py --role door
```

**Keyword search** across ref/package/group/name:
```bash
python .claude/skills/mesh-browser/scripts/query.py pipe
python .claude/skills/mesh-browser/scripts/query.py techdoor
```

**Within a package** (e.g. the tech kit):
```bash
python .claude/skills/mesh-browser/scripts/query.py --package HumanoidHardware
```

**By role or coarse bucket:**
```bash
python .claude/skills/mesh-browser/scripts/query.py --role machine
python .claude/skills/mesh-browser/scripts/query.py --bucket trim
```

**Overviews:**
```bash
python .claude/skills/mesh-browser/scripts/query.py --list-roles      # available roles + counts
python .claude/skills/mesh-browser/scripts/query.py --list-packages   # coverage + mesh/placement counts
```

**Useful flags:** `--limit N`, `--maps-limit N`, `--include-local` (see below),
`--json` (machine-readable, e.g. for the generator's mesh palette).

## Reading the results

- **Placement count is a prominence proxy**, not quality — a mesh placed 60×
  is structural; 1-2× is incidental.
- **Role is a heuristic** derived from the package/group/name (e.g. a `Doors`
  group or a `door` in the name → role `door`), not from geometry. It's a strong
  signal but spot-check the actual mesh in-editor. A "door" may be a door *leaf*
  or a door *frame* — the survey can't tell them apart, so confirm visually.
- **Map-local meshes are hidden by default** (`--include-local` to show them).
  They're baked into one map's package (ref reads `MapName.MeshName`) and **will
  not resolve if referenced from another map** — don't pick them for the generator.
- **Scale hint matters for placement.** Many meshes are routinely stretched
  (`DrawScale3D`) to fit; "often stretched" means expect to scale it. Across the
  set, **mesh yaw snaps to 90°** and **default 1:1 scale is the norm** except for
  structural spans — see `MESH_PATTERNS.md`.

## Wiring a door mesh to a Mover (the common task)

A `Mover` can use a static mesh instead of a brush — pure properties, so it
imports via T3D reliably:
```
DrawType=DT_StaticMesh
StaticMesh=StaticMesh'<package>.<group>.<name>'
DrawScale3D=(X=..,Y=..,Z=..)   # scale to fill the opening
Rotation=(Yaw=..)              # mesh-local width axis -> doorway width axis
KeyPos(1)=(Z=<open offset>)    # slide-open distance
InitialState=TriggerOpenTimed
```
See `import_kit/MonsterGate-Base-README.md` and `MONSTER_GATING.md` for the full
door + Counter wiring. Collision comes from the mesh, so prefer a solid door leaf.

## If the data is missing

```bash
python surveys/mesh_survey.py --json -o surveys/meshes.json
```

## Related

- `MESH_PATTERNS.md` — narrative findings + recommended tech mesh kit.
- `surveys/mesh_survey.py` — the extractor that builds `meshes.json`.
- `texture-browser` — the sibling skill for textures.
