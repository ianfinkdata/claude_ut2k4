# Lighting Patterns — UT2004 stock DM `Light` actors

Survey of every `Light` actor across the 39 stock UT2004 Deathmatch maps,
produced by [`surveys/lighting_survey.py`](surveys/lighting_survey.py) →
[`surveys/lighting.json`](surveys/lighting.json). Feeds the procedural light rig
the generator (Agent 7) stamps into each room module. Project theme is **tech /
industrial** (see `PLAN_MONSTERBASE.md`), so a tech subset (19 maps) is reported
alongside the full set.

Re-run: `python surveys/lighting_survey.py Maps/*.ut2` (or `--json`).

---

## How to read the data (serialization caveat)

The parser only emits a property when it **differs from the engine class
default**. An absent property = the default. The survey materializes these
defaults (UT2004 `Engine.Light` / `Actor`) before tallying, so a plain steady
light is still counted:

| Property | Class default | Notes |
|---|---|---|
| `LightType` | `LT_Steady` | absent on 99.3% of lights |
| `LightEffect` | `LE_None` (serialization archetype) | `LE_NonIncidence` is stored *explicitly* 723× as an override, proving it is **not** the archetype default; the runtime renders absent lights with the engine's own default |
| `LightBrightness` | 64 | |
| `LightHue` | 0 | 0 = no hue shift (white-ish) |
| `LightSaturation` | 255 | 255 = fully desaturated/white; lower = more colored |
| `LightRadius` | 64 | **units of 25 uu** → reach ≈ `LightRadius × 25` uu |
| `bDynamicLight` | false | |

Because most lights carry an explicit `LightEffect`, the rig rule keys off the
**explicit (authored) effect mix**, which is the choice a mapper actually makes.

---

## Cross-map distributions

### All 39 maps — 10,700 lights
- **Density:** avg **274 lights/map**; median **~14 lights per zone** (volume proxy = BSP `ZoneNumber`).
- **LightType:** **99% `LT_Steady`**. Animated types are rare (`LT_None` 0.7%, a handful of `LT_Flicker`/`LT_SubtlePulse`). Stock DM lighting is essentially all static-steady.
- **LightEffect (authored):** **89% no explicit effect**, then `LE_NonIncidence` 6%, `LE_StaticSpot` 2%, `LE_Cylinder` 1.5%, `LE_Spotlight` 0.4%, `LE_Sunlight` 0.1%.
- **Brightness:** median-of-medians **81**; pooled distribution p25–p75 ≈ **32–150**, common authored value **90**.
- **Radius:** explicit-radius median **16 units ≈ 400 uu reach** (p25 8 → 200uu, p75 32 → 800uu, p90 112 → 2800uu for the rare big fill lights).
- **Saturation:** median **~150** (clearly tinted); **88% of lights are colored** (saturation < 250). Stock lighting is *not* white.
- **Height above local floor:** median-of-medians **~145 uu** (lights sit a bit above head height; p25–p75 spans floor level up to ~ceiling).
- **Dynamic:** effectively **0** (2 across all maps). **Coronas** appear but are a minority accent.

### Tech / industrial subset — 19 maps, 6,086 lights
Same shape, slightly denser and more saturated:
- avg **320 lights/map**, median **16 lights/zone**.
- brightness median **81**, radius median **16 (≈400 uu)**.
- **81% colored**, saturation median **150**.
- height above floor median **~179 uu** (tech maps mount lights higher — wall sconces / ceiling fixtures).
- LightType **98% steady**; authored effect mix **85% none, 10% `LE_NonIncidence`**, then `LE_StaticSpot`/`LE_Cylinder`.

### Dominant hues (0–255 color wheel; 0 = white)
Pooled top hues, tech subset: **0 (white), 25–37 (warm amber/orange), 33, 45 (gold)**, then a cool cluster at **130–165 (cyan/teal/blue)**.

**The stock tech palette is a warm/cool split:** warm amber (`Hue 25–37`, low-ish saturation ~120–160) for the dominant fill, punctuated by cool teal/blue (`Hue 130–165`) accents — the classic industrial "sodium light + cold机 monitor glow" look. Pure-white (`Hue 0`) is the single most common bucket and reads as untinted fixtures.

---

## Parametric light-rig rule (generator input)

Given a room footprint `W × L` (uu) and ceiling height `H` (uu), emit a stock-
tech-feeling rig. All values are stock-derived; radius is in **engine 25-uu
units**.

### 1. Light count
Stock density is **~14–16 lights per zone**, and a zone ≈ one room. Scale by
floor area with a floor/ceiling clamp:

```
area     = W * L                      # uu^2
n_lights = clamp( round(area / 90000), 6, 18 )
```
(≈ one light per **300×300 uu** cell; 90000 ≈ the stock per-light footprint that
yields ~14/room for a typical ~1100×1100 room. Small rooms still get ≥6, large
arenas cap ~18 before it reads as overlit.)

### 2. Placement (grid + height)
- Lay lights on a roughly even grid across the footprint, inset ~128 uu from
  walls; jitter ±64 uu so it isn't mechanical.
- **Mounting height:** `floor_z + min(H − 32, 180)` — i.e. high on the wall /
  just under the ceiling (stock tech median height-above-floor ≈ **179 uu**;
  never within 32 uu of the ceiling).
- Optionally add 1–2 low **accent** lights (height ≈ floor + 32) near
  doorways/props for the cool-accent color (below).

### 3. Brightness / radius
- `LightType = LT_Steady` (always — 98–99% of stock).
- `LightBrightness = 90` for fill lights (stock authored mode), drop to **48–64**
  for accents.
- `LightRadius` so reach covers the cell with overlap: `radius_units =
  round( (cell_spacing * 0.75) / 25 )`, clamped to **8–40 units (200–1000 uu)**.
  Default fill ≈ **16 units (400 uu)**, matching the stock median.

### 4. Color (the tech look)
Assign per-light from a weighted palette (Hue 0–255, Saturation 0–255):

| Role | Weight | Hue | Saturation | Use |
|---|---|---|---|---|
| Warm fill | ~60% | 28–37 (amber) | 130–160 | dominant room lighting |
| White | ~25% | 0 | 200–255 | neutral fixtures |
| Cool accent | ~15% | 140–165 (teal/blue) | 120–160 | doorways, screens, depth |

Keep **~80% of lights colored** (saturation < 250) — stock tech maps are tinted,
not white.

### 5. Effect
- **~85% of lights: no `LightEffect`** (leave at engine default).
- Of the remainder, prefer `LE_NonIncidence` (the stock workhorse), then
  `LE_StaticSpot` / `LE_Cylinder` for spot/beam fixtures with `LightCone`
  (cone median ≈ **64**, range to 255). Reserve `LE_Spotlight`/`LE_Sunlight` for
  special cases.
- **No dynamic lights** (`bDynamicLight=false`), and animated types
  (`LT_Pulse`/`LT_Flicker`) only as deliberate one-off mood beats, not the rig.

### Worked example — 1024 × 1024 room, H = 384
- area = 1,048,576 → `n_lights = clamp(round(11.6), 6, 18) = 12`
- 4×3 grid, inset 128 uu, ±64 jitter; mount height = `floor + min(352,180) = floor + 180`
- spacing ≈ 256 uu → `radius_units = round(192/25)=8` clamped → ~12 units (~300uu) for tight overlap, or use the 16-unit default for softer fill
- ~7 warm-amber fill (Hue 32 / Sat 150 / Bri 90), ~3 white (Hue 0 / Sat 220 / Bri 90), ~2 cool accent (Hue 150 / Sat 140 / Bri 56) low near the doorways
- all `LT_Steady`, no explicit effect except optionally one `LE_NonIncidence` spot over the room's feature prop.

---

## Notable findings & parser notes

- **Stock DM lighting is static, dense, and tinted.** The defining traits to
  replicate: ~14–16 lights/room, all steady, ~80–88% colored, warm-amber
  dominant with cool accents, mounted high (~180 uu above floor), modest reach
  (~400 uu), almost no dynamic/animated lights, no effect on ~85%.
- **`LightRadius` is in 25-uu units**, not raw uu — easy to misread; the rig rule
  accounts for it.
- **Parser: no gaps found.** `read_properties` decodes every Light property
  needed (enums resolved via `schema.json`, `Region.ZoneNumber` available as a
  volume proxy, `Location`/`Rotation` clean). The only modeling assumption is the
  engine class defaults for absent properties (documented in `_DEFAULTS`); these
  are standard UT2004 `Engine.Light` defaults and are the correct
  interpretation of "property absent = default".
- **Zone as volume proxy:** BSP `ZoneNumber` (from each light's `Region`) is a
  good stand-in for "room/volume" for density; floor height per zone is taken
  from nav-node Z (PlayerStart/PathNode/InventorySpot sit on the floor).
- **Tech-map subset** is a hand-curated name list in the script
  (`_TECH_MAPS`); refine it once Agent 1's `TEXTURE_PATTERNS.md` lands with
  empirical theme clusters.
