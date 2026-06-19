---
name: texture-browser
description: >-
  Browse the texture/material usage data mined from the 39 stock UT2004 DM maps
  (surveys/textures.json). For any texture it surfaces the texture PACKAGE, the
  texture NAME (and group), and EXAMPLE MAPS that use it, ranked by how heavily
  each map uses it. Use this whenever the user wants to find, look up, compare,
  or pick UT2004 textures/materials — e.g. "what concrete textures do stock maps
  use?", "which maps use HumanoidArchitecture?", "show me floor textures",
  "find a good tech wall texture", "what package is bas02HAb in?", or any time
  you're choosing a texture palette for procedural map generation. Trigger it
  even when the user just describes a surface (rusty wall, sci-fi floor, trim)
  without naming a texture.
---

# Texture Browser

Browse how the stock UT2004 Deathmatch maps actually texture their geometry, so
texture choices are grounded in shipped maps instead of guesswork. The data comes
from `surveys/textures.json` (produced by `surveys/texture_survey.py`), which
records, per map, every material import and the per-texture brush-polygon counts
split by surface role (wall / floor / ceiling).

## When to use

Reach for this whenever the user is **finding, comparing, or choosing UT2004
textures** — by keyword ("concrete", "rust"), by package, or by surface role.
It's also the go-to when assembling a texture palette for the procedural
generator: it answers "which real textures fit this surface, and which stock maps
prove it works."

## How to run

The query script is stdlib-only Python and auto-locates `surveys/textures.json`
by walking up from the working directory (pass `--data <path>` to override).

```bash
python .claude/skills/texture-browser/scripts/query.py <term> [options]
```

Each result shows the **package**, **name** (and group), the texture's **dominant
surface role**, and the **example maps** that use it (most-prominent first, with
the polygon count in parentheses as a usage proxy).

### Common patterns

**Keyword search** — match across full ref / package / group / name:
```bash
python .claude/skills/texture-browser/scripts/query.py concrete
python .claude/skills/texture-browser/scripts/query.py rust
```

**Within a package** — list everything in one package, ranked by total usage:
```bash
python .claude/skills/texture-browser/scripts/query.py --package HumanoidArchitecture
```

**By surface role** — only textures whose dominant role is wall/floor/ceiling:
```bash
python .claude/skills/texture-browser/scripts/query.py --role floor
python .claude/skills/texture-browser/scripts/query.py rust --role wall
```

**Package overview** — coverage (how many maps) + texture/poly counts per package:
```bash
python .claude/skills/texture-browser/scripts/query.py --list-packages
```

**Useful flags:** `--limit N` (max textures, default 40), `--maps-limit N`
(example maps per texture, default 6), `--json` (machine-readable output for
feeding into other tooling, e.g. the generator's palette selection).

## Reading the results

- **Polygon counts are a prominence proxy**, not a quality score: a texture with
  thousands of polys is a primary surface in that map; a handful of polys is an
  accent or incidental use.
- **Dominant role can be surprising.** Many `Bases.*`/`Floors.*` textures are
  tiling sheets applied to *walls* more than floors, so a "floor"-named texture
  may report `[wall]`. That reflects real shipped usage — trust the data over the
  name. Use `--role` to filter by how textures are actually used, not how they're
  named.
- **Single-map textures** (e.g. `Futuretech1.*` appears only in DM-Injector) are
  niche; broad palettes come from packages with high map coverage
  (`--list-packages`). For the project's tech theme, `HumanoidArchitecture` /
  `AbaddonArchitecture` are the high-coverage backbone — see `TEXTURE_PATTERNS.md`.

## If the data is missing

If the script can't find `surveys/textures.json`, regenerate it from the maps:
```bash
python surveys/texture_survey.py --json -o surveys/textures.json
```

## Related

- `TEXTURE_PATTERNS.md` — the narrative findings + recommended tech palette.
- `surveys/texture_survey.py` — the extractor that builds `textures.json`.
- `PLAN_MONSTERBASE.md` — how texture palettes feed the procedural generator.
