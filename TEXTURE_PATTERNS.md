# TEXTURE_PATTERNS.md — texture/material survey of the 39 stock DM maps

Agent #1 (texture-cartographer) findings. Regenerate the data with:

```
python surveys/texture_survey.py Maps/DM-*.ut2 --json > surveys/textures.json
python surveys/texture_survey.py Maps/DM-*.ut2            # human report
```

`surveys/texture_survey.py` mines two signals per map and clusters across maps:

1. **Material catalog** — every Texture/Shader/Combiner/... a map references from
   the import table, as a dotted `Package.Group.Name` path. (What art a map *can*
   draw on.)
2. **Per-surface usage** — every editor-brush polygon carries a `Texture` ref and
   a face normal. The normal classifies the face into **floor** (Nz > 0.7),
   **ceiling** (Nz < -0.7) or **wall**, and the refs are counted per role. (What
   art a map *actually paints*, and on which surface role.)

Scope note: the survey ran over the 39 stock `DM-*.ut2`. `claude_test_skeleton.ut2`
is the user's playtest room (non-stock) and is excluded from the cross-map stats;
it is referenced separately below as the already-validated anchor palette.

---

## 1. Which packages dominate

Across all 39 maps, **3.1 M+ poly→texture assignments resolve to ~70 source
packages**, but usage is extremely concentrated. Architectural texture polys
(excluding skies, coronas, emitter/flare sprites, detail overlays and the
`Engine` default) break down as:

| Package | % of arch polys | maps | role skew (floor/wall/ceiling) |
|---|---|---|---|
| **HumanoidArchitecture** | **28%** | **20 / 39** | 17 / 62 / 19 |
| **AbaddonArchitecture** | 14% | 17 / 39 | — |
| **HumanoidArchitecture2** | 8% | 10 / 39 | — |
| **H_E_L_Ltx** | 6% | 10 / 39 | — |
| Shiptech | 5% | 12 / 39 | — |
| BarrensArchitecture | 4% | 4 | — |
| Phobos2_cp | 4% | 3 | 20 / 61 / 17 |
| cp_Evil3 | 2% | 4 | 14 / 71 / 14 |
| ArboreaArchitecture | 2% | 2 | 18 / 59 / 22 (terrain/organic) |
| AlleriaArchitecture | 2% | 6 | 15 / 72 / 12 |

Two facts drive everything downstream:

- **HumanoidArchitecture is the lingua franca of stock UT2004 DM.** It is on the
  plurality of maps and supplies ~28% of all architectural surface area. Its
  sibling `HumanoidArchitecture2` and the closely-paired `AbaddonArchitecture`
  push the "Humanoid/Abaddon tech" family well past half of all painted
  geometry. These are **the** tech/industrial texture sets.
- **Surface-role split is stable (~15-20% floor / ~60-72% wall / ~10-20%
  ceiling).** Walls dominate every package. The generator should budget texture
  variety accordingly: walls carry the visual identity; floors/ceilings are
  fewer, larger faces.

Most-frequently-painted single textures (any package, all roles):
`HumanoidArchitecture.Bases.bas02HAb`, `.Bases.bas06HAb`,
`HumanoidArchitecture2.Bases.bas05dHA`, `AbaddonArchitecture.Base.bas12go`,
`HumanoidArchitecture.Borders.bdr02HA`, `HumanoidArchitecture.Floors.flr03HA`.
Note the workhorse `Bases.*` textures are tiling panel sheets used on *both*
walls and floors; dedicated `Floors.*` / `Borders.*` / `Grates.*` groups exist
for role-specific surfaces and trim.

---

## 2. Theme clusters

Maps clustered by Jaccard similarity of their dominant architectural packages
(packages ≥10% of a map's arch polys). The big buckets:

### Tech / industrial — Humanoid·Abaddon family (the project theme) — ~17 maps
The two largest clusters share **HumanoidArchitecture** and pair it with
`HumanoidArchitecture2`, `AbaddonArchitecture`, and `H_E_L_Ltx`:

- **Cluster 1 (9 maps):** Rankin, Compressed, Plunge, Morpheus3, DE-Ironic,
  1on1-Idoma, 1on1-Mixer, 1on1-Roughinery, 1on1-Trite.
- **Cluster 2 (5 maps):** Metallurgy, Corrugation, Gael, Leviathan, Asbestos.
- Plus tech outliers that lean on the same/adjacent sets: **Deck17**
  (HumanoidArchitecture + AlleriaArchitecture + `X_cp_Evil3`), **Curse4**
  (Humanoid + BarrensArchitecture-epic + H_E_L_Ltx), **Injector** (Futuretech1 +
  HumanoidArchitecture2 + Mech/Evil sets), **IronDeity** (`CP_UT2K3_TechSet1` +
  cp_Evil3).

This is the **Rankin / Deck17 / Metallurgy family** called out in the brief, and
it is by a wide margin the most-represented look in the stock DM set. **It is the
correct anchor for the generator's tech theme.**

### Other (non-tech, for reference / negative selection)
- **Egyptian / stone:** 1on1-Serpentine + DE-Osiris2 (BarrensArchitecture),
  DesertIsle.
- **Organic / terrain / outdoor:** 1on1-Spirit + Antalus (ArboreaArchitecture),
  Icetomb, Junkyard (AW-Metals/cp_Junkyard — junk-tech, adjacent).
- **Ship / hull:** 1on1-Crash + Oceanic (Shiptech/Shiptech2), Goliath, Phobos2
  (Phobos2_cp + Shiptech — space-station tech, adjacent).
- **Alleria tech:** 1on1-Squader, Flux2, HyperBlast2 (AlleriaArchitecture —
  clean sci-fi, adjacent to the tech theme).

### Package co-occurrence (top edges)
`AbaddonArchitecture + HumanoidArchitecture` (11 maps),
`AbaddonArchitecture + Shiptech` (9), `HumanoidArchitecture +
HumanoidArchitecture2` (9). The Humanoid↔Abaddon link is the strongest in the
set — they are designed to mix, which is why the tech family reads as one theme.

---

## 3. Recommended tech palette for the generator

Two layers: a **statistical core** (what the dominant stock tech maps actually
paint — maximum coverage, guaranteed-present art) and the **project anchor**
(the Chrome/Futuretech look already validated in the playtest room). Pick the
core for fidelity to stock DM; layer the anchor for the chosen project identity.

### 3a. Statistical core palette — Humanoid·Abaddon tech
Assign by surface role (texture names are real, verified by poly frequency in the
tech-family maps). All paths are `Package.Group.Name`:

| Surface role | Primary | Alternates |
|---|---|---|
| **Floor** | `HumanoidArchitecture.Floors.flr03HA` | `HumanoidArchitecture.Floors.flr08HA`, `HumanoidArchitecture2.Bases.bas05dHA` |
| **Wall** | `HumanoidArchitecture.Bases.bas02HAb` | `AbaddonArchitecture.Base.bas12go`, `HumanoidArchitecture2.Bases.bas05dHA`, `HumanoidArchitecture.Bases.bas02HA` |
| **Ceiling** | `HumanoidArchitecture.Floors.flr03HA` | `HumanoidArchitecture.Floors.flr08HA`, `AbaddonArchitecture.Floors.flr17go` |
| **Trim / border** | `HumanoidArchitecture.Borders.bdr02HA` | `HumanoidArchitecture2.Borders.bdr02bHA` |
| **Grate / vent (accent)** | `HumanoidArchitecture.Grates.*` | — |

Rationale: every one of these appears in multiple stock tech maps with high poly
counts, so they tile correctly and read as a coherent set. `bas*` panels are the
do-everything wall sheets; `flr*` reads cleanly overhead as well as underfoot;
`bdr*` borders are the natural module-edge trim.

### 3b. Project anchor palette — Chrome / Futuretech (playtest-validated)
The playtest room (`claude_test_skeleton.ut2`) already ships textured + lit with:

| Surface role | Texture / shader |
|---|---|
| **Floor / structural** | `Futuretech1.Base.concrete1c` (also `Futuretech1.Base.concrete3` — the dominant face in DM-Injector) |
| **Wall** | `Chrome_cp.Walls.cp_chromebase1` |
| **Wall (shaded variant)** | `Chrome_cp.Walls.cp_chrometechwallshad` (Shader), `Chrome_cp.Walls.cp_chromebase1shad` (Shader) |
| **Wall accent** | `Chrome_cp.Walls.cp_chrometechwallblu` (the painted face in DM-Goliath) |

Caveat worth flagging to the user: **`Chrome_cp` and `Futuretech1` are rare in
the stock DM set** — Futuretech1 is painted only in DM-Injector and Chrome_cp
only in DM-Goliath. They are a legitimate UT2004 tech look (and the team has
already committed to them in the playtest room), but they are an *aesthetic*
pick, not the statistical center of stock DM tech. If the goal is "looks like a
stock DM tech map," lean on 3a; if it's "matches the playtest room we've already
built and lit," lean on 3b. Recommended default: **3a core + 3b chrome accents on
hero walls / trim**, so modules read as Humanoid-tech with the project's chrome
signature.

### 3c. Generator wiring
- Theme tag `tech` → this palette. A module's surfaces get assigned by role
  (floor/wall/ceiling/trim) using the table above; vary within the alternates
  column per-module for visual rhythm without breaking the family.
- Budget variety toward walls (~60-70% of faces) and keep floor/ceiling to 1-2
  textures each per module — matches the observed stock distribution.
- All packages here are stock UT2004 content already loaded by other DM maps, so
  the engine will resolve the refs at import/build without extra dependencies.

---

## Parser notes / limitations

- **No parser bugs found.** `ut2parser.py` decoded brush polygons and resolved
  texture refs cleanly across all 39 maps (no `ParseError`, no decode gaps in the
  survey run).
- **Per-surface data comes only from editor-brush polygons** (`Brush` actors with
  a resolvable `Model → Polys`). Texture assignments baked into static meshes,
  terrain layers, or built-BSP-only volumes are *not* in the per-surface counts —
  static-mesh skins are Agent #3's domain. The import-table catalog still lists
  those material packages, so nothing is invisible; it just isn't attributed to a
  floor/wall/ceiling face.
- **Surface-role classification is geometric** (face normal), not semantic. A
  slanted ramp face counts as "wall"; a thin trim strip on a wall counts toward
  wall area. Good enough for palette budgeting; not a substitute for Agent #5's
  geometry survey.
- **Map-local textures** (e.g. `DM-Rankin.shaiBricks1b`) show up under the map's
  own package name and are excluded from cross-map architectural rankings — they
  can't be reused by the generator anyway.
