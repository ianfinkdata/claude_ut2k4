#!/usr/bin/env python3
"""Light-actor survey across the UT2004 stock DM map inventory.

Mines repeatable lighting structure from the stock maps so the generator
(Agent 7) can build a stock-feeling light rig for a procedural room:
 - per-Light property recovery (LightType/LightEffect/LightBrightness/LightHue/
   LightSaturation/LightRadius/LightCone + falloff/corona, bDynamicLight)
 - placement characterization (lights per zone/volume, height above the local
   floor, color/effect usage)
 - cross-map distributions + a "tech / industrial" subset, since the project's
   locked theme is tech (see PLAN_MONSTERBASE.md).

The parser only serializes a property when it DIFFERS from the engine class
default, so an absent property means "default value". We fill defaults from
UT2004's Engine.Light/Actor class defaults (see _DEFAULTS) before computing
distributions, otherwise the common case (a plain steady light) is invisible.

Run:  python surveys/lighting_survey.py Maps/*.ut2           # full report
      python surveys/lighting_survey.py Maps/DM-Rankin.ut2   # one map
      python surveys/lighting_survey.py Maps/*.ut2 --json     # machine-readable
"""

from __future__ import annotations

import glob
import math
import os
import statistics
from collections import Counter, defaultdict

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut2parser as u  # noqa: E402

# --------------------------------------------------------------------------- #
# Engine class defaults for Light properties (UT2004 Engine.Light / Actor).
# A property absent from an actor's tagged-property list means it equals the
# class default; we materialize these so "plain" lights are counted correctly.
# --------------------------------------------------------------------------- #
_DEFAULTS = {
    "LightType": "LT_Steady",       # absent ~99% of the time -> steady
    "LightEffect": "LE_NonIncidence",  # see note below
    "LightBrightness": 64.0,
    "LightHue": 0,
    "LightSaturation": 255,          # 255 = white/desaturated
    "LightRadius": 64.0,
    "LightCone": 0,
    "LightPeriod": 0,
    "LightPhase": 0,
    "bDynamicLight": False,
    "bCorona": False,
    "bSpecialLit": False,
    "bDirectional": False,
}
# NOTE on LightEffect default: the tagged-property stream stores LE_NonIncidence
# explicitly 723x as a NON-default override, which means the serialization
# archetype default is LE_None (index 0). For replication fidelity we therefore
# treat an ABSENT LightEffect as LE_None when tallying "explicit" effects, but
# the engine renders absent lights with its runtime default. We report both the
# explicit-effect mix and the absent count so the generator can decide. The
# light-rig rule below keys off the explicit (authored) effects, which is what a
# mapper actually chooses.
_LIGHTEFFECT_ABSENT = "LE_None(absent/default)"

# Tech / industrial stock DM maps (locked project theme). Chosen by their
# texture families (Chrome/Futuretech/metal/industrial) vs. organic/egyptian/
# alien/space themes. Used to derive a theme-specific rig.
_TECH_MAPS = {
    "DM-Rankin", "DM-1on1-Roughinery", "DM-Corrugation", "DM-Injector",
    "DM-Metallurgy", "DM-Compressed", "DM-Gestalt", "DM-1on1-Idoma",
    "DM-1on1-Irondust", "DM-1on1-Mixer", "DM-1on1-Squader", "DM-Goliath",
    "DM-IronDeity", "DM-Junkyard", "DM-Phobos2", "DM-HyperBlast2",
    "DM-DE-Ironic", "DM-Icetomb", "DM-1on1-Crash",
}

# Light subclasses worth distinguishing if present (stock DM uses bare Light).
_LIGHT_CLASSES = {"Light", "TriggerLight", "Sunlight", "SpotLight"}


def _enum_str(v):
    """EnumValue/str -> bare identifier string."""
    return str(v) if v is not None else None


def _light_record(pkg, e):
    """Extract one Light actor's surveyed properties, defaults filled in."""
    props = {p.name: p.value for p in u.read_properties(pkg, e)}
    rec = {}
    for k, dflt in _DEFAULTS.items():
        rec[k] = props.get(k, dflt)
    # normalize enums to plain strings
    rec["LightType"] = _enum_str(rec["LightType"])
    rec["LightEffect_explicit"] = (
        _enum_str(props["LightEffect"]) if "LightEffect" in props
        else _LIGHTEFFECT_ABSENT
    )
    rec["LightEffect"] = _enum_str(rec["LightEffect"])
    loc = props.get("Location")
    rec["location"] = list(loc) if isinstance(loc, tuple) else None
    reg = props.get("Region")
    rec["zone"] = reg.get("ZoneNumber") if isinstance(reg, dict) else None
    rec["bCorona"] = bool(props.get("bCorona", False))
    rec["has_explicit_radius"] = "LightRadius" in props
    rec["has_explicit_brightness"] = "LightBrightness" in props
    return rec


def _floor_z_by_zone(pkg):
    """Floor-Z reference per zone, from nav nodes (PlayerStart/PathNode/
    InventorySpot sit ~on the floor). Returns {zone: floor_z} and a global
    fallback floor Z (overall nav minimum)."""
    by_zone = defaultdict(list)
    all_z = []
    for e in pkg.exports:
        if e.class_name in ("PlayerStart", "PathNode", "InventorySpot",
                            "JumpSpot", "JumpDest"):
            props = {p.name: p.value for p in u.read_properties(pkg, e)}
            reg = props.get("Region")
            loc = props.get("Location")
            if isinstance(loc, tuple):
                all_z.append(loc[2])
                if isinstance(reg, dict):
                    by_zone[reg.get("ZoneNumber")].append(loc[2])
    floor = {z: statistics.median(v) for z, v in by_zone.items() if v}
    global_floor = min(all_z) if all_z else None
    return floor, global_floor


def analyze(path: str) -> dict:
    stem = os.path.splitext(os.path.basename(path))[0]
    pkg = u.parse(open(path, "rb").read(), stem)
    floor_by_zone, global_floor = _floor_z_by_zone(pkg)

    lights = []
    for e in pkg.exports:
        if e.class_name in _LIGHT_CLASSES:
            rec = _light_record(pkg, e)
            rec["_class"] = e.class_name
            lights.append(rec)

    n = len(lights)
    brightness = [r["LightBrightness"] for r in lights]
    radius = [r["LightRadius"] for r in lights]
    hue = Counter(r["LightHue"] for r in lights)
    sat = [r["LightSaturation"] for r in lights]
    cone = [r["LightCone"] for r in lights if r["LightCone"]]
    type_mix = Counter(r["LightType"] for r in lights)
    effect_explicit = Counter(r["LightEffect_explicit"] for r in lights)

    # placement: lights per zone (volume proxy) and height above local floor
    per_zone = Counter()
    heights = []
    for r in lights:
        z = r["zone"]
        if z is not None:
            per_zone[z] += 1
        if r["location"] is not None:
            fz = floor_by_zone.get(z, global_floor)
            if fz is not None:
                heights.append(r["location"][2] - fz)

    colored = sum(1 for r in lights if r["LightSaturation"] < 250)
    dynamic = sum(1 for r in lights if r["bDynamicLight"])
    corona = sum(1 for r in lights if r["bCorona"])

    def s(x):
        if not x:
            return {"min": 0, "median": 0, "mean": 0, "max": 0, "p25": 0, "p75": 0}
        sx = sorted(x)
        return {
            "min": round(min(sx), 1), "max": round(max(sx), 1),
            "median": round(statistics.median(sx), 1),
            "mean": round(statistics.mean(sx), 1),
            "p25": round(sx[len(sx) // 4], 1),
            "p75": round(sx[(len(sx) * 3) // 4], 1),
        }

    lights_per_zone = sorted(per_zone.values())
    return {
        "map": os.path.basename(path),
        "stem": stem,
        "tech": stem in _TECH_MAPS,
        "light_count": n,
        "class_mix": dict(Counter(r["_class"] for r in lights)),
        "brightness": s(brightness),
        "radius": s(radius),
        "saturation": s(sat),
        "cone_count": len(cone),
        "cone": s(cone),
        "type_mix": dict(type_mix),
        "effect_explicit_mix": dict(effect_explicit),
        "top_hues": hue.most_common(8),
        "colored_pct": round(100 * colored / n, 1) if n else 0,
        "dynamic_count": dynamic,
        "corona_count": corona,
        "zones_with_light": len(per_zone),
        "lights_per_zone_median": (statistics.median(lights_per_zone)
                                   if lights_per_zone else 0),
        "lights_per_zone_max": max(lights_per_zone) if lights_per_zone else 0,
        "height_above_floor": s(heights),
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def print_one(a: dict) -> None:
    tech = " [TECH]" if a["tech"] else ""
    print(f"\n== {a['map']}{tech} ==")
    print(f"  lights: {a['light_count']}   zones lit: {a['zones_with_light']}"
          f"   lights/zone median={a['lights_per_zone_median']} max={a['lights_per_zone_max']}")
    b, r = a["brightness"], a["radius"]
    print(f"  brightness: med={b['median']} (p25-p75 {b['p25']}-{b['p75']}, max {b['max']})"
          f"   radius: med={r['median']} (p25-p75 {r['p25']}-{r['p75']}, max {r['max']})")
    print(f"  saturation: med={a['saturation']['median']}  colored(<250sat): {a['colored_pct']}%"
          f"   corona: {a['corona_count']}   dynamic: {a['dynamic_count']}")
    h = a["height_above_floor"]
    print(f"  height above local floor: med={h['median']} (p25-p75 {h['p25']}-{h['p75']})")
    print(f"  type mix: {a['type_mix']}")
    print(f"  effect (explicit) mix: {a['effect_explicit_mix']}")
    print(f"  top hues: {a['top_hues']}")


def _agg_stat(results, key):
    """Median of a per-map stat's medians, plus pooled min/max."""
    meds = [r[key]["median"] for r in results if r["light_count"]]
    return {
        "median_of_medians": round(statistics.median(meds), 1) if meds else 0,
        "min": min((r[key]["min"] for r in results if r["light_count"]), default=0),
        "max": max((r[key]["max"] for r in results if r["light_count"]), default=0),
    }


def cross_map(results, label):
    n = len(results)
    tot_lights = sum(r["light_count"] for r in results)
    type_mix = Counter()
    eff_mix = Counter()
    hue = Counter()
    for r in results:
        for k, v in r["type_mix"].items():
            type_mix[k] += v
        for k, v in r["effect_explicit_mix"].items():
            eff_mix[k] += v
        for k, v in r["top_hues"]:
            hue[k] += v
    colored = statistics.median([r["colored_pct"] for r in results]) if results else 0
    return {
        "label": label,
        "maps": n,
        "total_lights": tot_lights,
        "avg_lights_per_map": round(tot_lights / n, 1) if n else 0,
        "lights_per_zone_median": (statistics.median(
            [r["lights_per_zone_median"] for r in results]) if results else 0),
        "brightness": _agg_stat(results, "brightness"),
        "radius": _agg_stat(results, "radius"),
        "saturation": _agg_stat(results, "saturation"),
        "cone": _agg_stat(results, "cone"),
        "height_above_floor": _agg_stat(results, "height_above_floor"),
        "colored_pct_median": round(colored, 1),
        "type_mix": dict(type_mix),
        "effect_explicit_mix": dict(eff_mix.most_common()),
        "top_hues": hue.most_common(12),
    }


def _bar(n, total, width=24):
    return "#" * int(round(width * n / total)) if total else ""


def print_summary(results) -> None:
    for label, subset in (("ALL MAPS", results),
                          ("TECH / INDUSTRIAL SUBSET",
                           [r for r in results if r["tech"]])):
        if not subset:
            continue
        c = cross_map(subset, label)
        print("\n" + "=" * 70)
        print(f"{c['label']}  ({c['maps']} maps, {c['total_lights']} lights)")
        print("=" * 70)
        print(f"avg lights/map: {c['avg_lights_per_map']}   "
              f"median lights/zone: {c['lights_per_zone_median']}")
        print(f"brightness: median-of-medians={c['brightness']['median_of_medians']}"
              f"  (range {c['brightness']['min']}-{c['brightness']['max']})")
        print(f"radius:     median-of-medians={c['radius']['median_of_medians']}"
              f"  (range {c['radius']['min']}-{c['radius']['max']})")
        print(f"saturation: median-of-medians={c['saturation']['median_of_medians']}"
              f"   colored(<250): {c['colored_pct_median']}% of lights")
        print(f"height above floor: median-of-medians={c['height_above_floor']['median_of_medians']}")
        tot_t = sum(c["type_mix"].values())
        print(f"\nLightType mix ({tot_t} lights):")
        for k, v in sorted(c["type_mix"].items(), key=lambda x: -x[1]):
            print(f"  {k:18s} {v:6d}  {100*v//tot_t:3d}%  {_bar(v, tot_t)}")
        tot_e = sum(c["effect_explicit_mix"].values())
        print(f"\nLightEffect (explicit/authored) mix ({tot_e}):")
        for k, v in c["effect_explicit_mix"].items():
            print(f"  {k:26s} {v:6d}  {100*v//tot_e:3d}%  {_bar(v, tot_e)}")
        print(f"\nTop hues (0=white-ish, 0-255 wheel): {c['top_hues']}")


def main(argv):
    files = [f for f in argv if not f.startswith("--")]
    # stock survey excludes the working test skeleton
    files = [f for f in files if "claude_test" not in os.path.basename(f)]
    as_json = "--json" in argv
    results = [analyze(f) for f in files]
    if as_json:
        import json
        out = {
            "per_map": results,
            "cross_map": {
                "all": cross_map(results, "ALL MAPS"),
                "tech": cross_map([r for r in results if r["tech"]],
                                  "TECH / INDUSTRIAL SUBSET"),
            },
        }
        print(json.dumps(out, indent=2))
        return 0
    for a in results:
        print_one(a)
    if len(results) > 1:
        print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
