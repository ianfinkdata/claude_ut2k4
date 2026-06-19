#!/usr/bin/env python3
"""Coordinate-level survey of pickup placement + nav-node spatial distribution.

This is the deep COORDINATE companion to `navanalysis.py` (Agent #4 of the
procedural-map plan). `navanalysis.py` establishes the graph-level invariants
(1:1 InventorySpot:pickup, out-degree ~4.2, walk_gap<1200, edge-type mix);
this script answers WHERE things sit in space:

  * pickup placement vs geometry: height above its nav node (floor proxy),
    distance to nearest nav node, distance to nearest wall (BlockingVolume/
    brush proxy), spacing to the nearest other pickup, per-category spread
  * HIGH-VALUE anchoring (weapon / powerup / armor): centrality (distance from
    the map's nav centroid, normalised by map radius), elevation band, distance
    to the nearest PlayerStart -- the direct inputs to reward-gating placement
  * nav-node spatial distribution: per-floor (256uu Z-band) node density, the
    realised walk-gap distribution (full histogram, not just the global max),
    and how InventorySpots tie into the graph (out-degree, isolation)

Pickup<->InventorySpot matching is EXACT, not proximity-based: every pickup
carries `myMarker` -> its InventorySpot, and the spot carries `myPickupBase`
back. (Confirmed present on all 2194 pickups across the 39 stock maps.)

Run:  python surveys/pickup_coords.py Maps/*.ut2            # report
      python surveys/pickup_coords.py Maps/*.ut2 --json     # dataset
      python surveys/pickup_coords.py Maps/*.ut2 --json -o surveys/pickup_coords.json

Stdlib only. Built on ut2parser. Does not modify navanalysis.py behaviour.
"""

from __future__ import annotations

import glob
import math
import os
import statistics
import sys
from collections import Counter, defaultdict

# allow running from repo root or from surveys/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut2parser as u  # noqa: E402
import navanalysis as na  # noqa: E402

# High-value categories that drive reward-gating placement.
HIGH_VALUE = {"weapon", "powerup", "armor"}

# Weapons treated as "premium" rewards in the monster-base concept.
PREMIUM_WEAPONS = {"Redeemer", "Painter", "ClassicSniperRifle"}

# Wall proxies: actors whose presence bounds the playable space. BlockingVolume
# is the cleanest signal (invisible collision walls); we also fall back to the
# nav bounding box edge when no blocking volume is near.
WALL_CLASSES = {"BlockingVolume"}


def _classify(cls: str):
    """Pickup category, extending navanalysis with WildCardBase (a weapon spawn
    base used by mutator/wildcard modes -- it hosts a weapon, so: weapon)."""
    cat = na._classify_pickup(cls)
    if cat is None and cls == "WildCardBase":
        return "weapon"
    return cat


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _dist2_xy(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * q
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(sorted_vals[lo])
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def analyze(path: str) -> dict:
    pkg = u.parse(open(path, "rb").read(),
                  os.path.splitext(os.path.basename(path))[0])

    # --- gather placed actors with locations + the links we need -----------
    loc_by_idx = {}            # export idx (1-based) -> (class, location)
    nav_locs = []              # locations of every NavigationPoint node
    nav_idx = {}               # idx -> location (nav nodes only)
    invspot_pathlen = {}       # InventorySpot idx -> out-degree
    playerstarts = []          # PlayerStart locations
    walls = []                 # BlockingVolume locations (wall proxy)
    pickups = []               # dicts, one per pickup actor
    marker_loc = {}            # InventorySpot idx -> location

    for i, e in enumerate(pkg.exports):
        idx = i + 1
        props = {p.name: p.value for p in u.read_properties(pkg, e)}
        loc = props.get("Location")
        if loc is None:
            continue
        loc_by_idx[idx] = (e.class_name, loc)
        if e.class_name in WALL_CLASSES:
            walls.append(loc)
        if e.class_name == "PlayerStart":
            playerstarts.append(loc)
        is_nav = e.class_name in na.NAV_CLASSES or "PathList" in props
        if is_nav:
            nav_idx[idx] = loc
            nav_locs.append(loc)
        if e.class_name == "InventorySpot":
            marker_loc[idx] = loc
            pl = props.get("PathList")
            invspot_pathlen[idx] = (
                len([el for el in pl if isinstance(el, u.ObjectRef)])
                if isinstance(pl, list) else 0)

    # second pass: pickups (need marker_loc fully built for matching)
    for i, e in enumerate(pkg.exports):
        idx = i + 1
        if idx not in loc_by_idx:
            continue
        cls, loc = loc_by_idx[idx]
        cat = _classify(cls)
        if not cat:
            continue
        props = {p.name: p.value for p in u.read_properties(pkg, e)}
        marker = props.get("myMarker") or props.get("MyMarker")
        mref = marker.ref if isinstance(marker, u.ObjectRef) else None
        spot_loc = marker_loc.get(mref)
        wtype = props.get("WeaponType")
        pickups.append({
            "idx": idx, "class": cls, "category": cat,
            "loc": list(loc),
            "spot_idx": mref,
            "spot_loc": list(spot_loc) if spot_loc else None,
            "weapon_type": str(wtype) if wtype is not None else None,
            "spot_out_degree": invspot_pathlen.get(mref),
        })

    # --- map frame: nav bounding box, centroid, radius ---------------------
    if not nav_locs:
        return {"map": os.path.basename(path), "error": "no nav nodes"}
    xs = [l[0] for l in nav_locs]
    ys = [l[1] for l in nav_locs]
    zs = [l[2] for l in nav_locs]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    cz = statistics.median(zs)
    # map radius = max XY distance from centroid to any nav node (normaliser)
    map_radius = max((math.hypot(l[0] - cx, l[1] - cy) for l in nav_locs),
                     default=1.0) or 1.0
    z_min, z_max = min(zs), max(zs)
    z_span = (z_max - z_min) or 1.0

    # floor bands (256uu Z buckets, same convention as navanalysis)
    def band(z):
        return int((z - z_min) // 256)
    floor_node_counts = Counter(band(l[2]) for l in nav_locs)
    n_floors = len(floor_node_counts)

    # --- per-pickup geometry ----------------------------------------------
    nav_pts = list(nav_idx.values())
    for p in pickups:
        loc = tuple(p["loc"])
        # height of the item base above its nav node's floor-snapped Z.
        # The InventorySpot is floor-snapped at pawn-center height; pickup mesh
        # base sits below it. We report the signed delta (pickup_z - spot_z) and
        # an elevation band relative to the map's lowest floor.
        if p["spot_loc"]:
            p["z_above_spot"] = round(loc[2] - p["spot_loc"][2], 1)
            # distance pickup->its own spot (anchoring tightness, XY + full)
            p["spot_xy_dist"] = round(math.sqrt(_dist2_xy(loc, tuple(p["spot_loc"]))), 1)
        else:
            p["z_above_spot"] = None
            p["spot_xy_dist"] = None
        p["floor_band"] = band(loc[2])
        # normalised elevation: 0 = map floor, 1 = ceiling of nav extent
        p["elev_norm"] = round((loc[2] - z_min) / z_span, 3)
        # nearest nav node (excluding its own spot)
        nd = [math.sqrt(_dist2(loc, n)) for n in nav_pts
              if _dist2(loc, n) > 1.0]
        p["nearest_nav_dist"] = round(min(nd), 1) if nd else None
        # nearest wall (BlockingVolume); None if map has none
        if walls:
            p["nearest_wall_dist"] = round(
                min(math.sqrt(_dist2_xy(loc, w)) for w in walls), 1)
        else:
            p["nearest_wall_dist"] = None
        # nearest PlayerStart (spawn) -- contestedness/exposure proxy
        if playerstarts:
            p["nearest_spawn_dist"] = round(
                min(math.sqrt(_dist2(loc, s)) for s in playerstarts), 1)
        else:
            p["nearest_spawn_dist"] = None
        # centrality: 0 = dead-centre, 1 = at the map edge
        p["centrality"] = round(math.hypot(loc[0] - cx, loc[1] - cy) / map_radius, 3)

    # nearest OTHER pickup (spacing/clustering) -- per category and overall
    plocs = [tuple(p["loc"]) for p in pickups]
    for i, p in enumerate(pickups):
        loc = plocs[i]
        nn = [math.sqrt(_dist2(loc, plocs[j]))
              for j in range(len(plocs)) if j != i]
        p["nearest_pickup_dist"] = round(min(nn), 1) if nn else None
        # nearest same-category pickup
        same = [math.sqrt(_dist2(loc, plocs[j]))
                for j, q in enumerate(pickups)
                if j != i and q["category"] == p["category"]]
        p["nearest_same_cat_dist"] = round(min(same), 1) if same else None

    # --- realised walk-gap distribution (full, not just the max) ----------
    # rebuild walk edges with distances from ReachSpecs (same source as navanalysis)
    walk_dists = []
    for e in pkg.exports:
        if e.class_name != "ReachSpec":
            continue
        props = {p.name: p.value for p in u.read_properties(pkg, e)}
        flags = props.get("reachFlags", 0) or 0
        d = props.get("Distance", 0)
        if (flags & 1) and d:
            walk_dists.append(d)
    walk_dists.sort()

    def cat_stats(values):
        if not values:
            return None
        s = sorted(values)
        return {
            "n": len(s), "min": round(s[0], 1),
            "p25": round(_pct(s, 0.25), 1), "median": round(statistics.median(s), 1),
            "p75": round(_pct(s, 0.75), 1), "p90": round(_pct(s, 0.90), 1),
            "max": round(s[-1], 1), "mean": round(statistics.fmean(s), 1),
        }

    # per-category aggregate of the key geometry metrics
    by_cat = defaultdict(lambda: defaultdict(list))
    for p in pickups:
        c = p["category"]
        for m in ("z_above_spot", "nearest_nav_dist", "nearest_wall_dist",
                  "nearest_pickup_dist", "nearest_same_cat_dist",
                  "nearest_spawn_dist", "centrality", "elev_norm"):
            if p.get(m) is not None:
                by_cat[c][m].append(p[m])
    cat_summary = {c: {m: cat_stats(v) for m, v in metrics.items()}
                   for c, metrics in by_cat.items()}

    # InventorySpot graph integration
    spot_degrees = [d for d in invspot_pathlen.values()]
    iso_spots = sum(1 for d in spot_degrees if d < 2)

    # walk-gap histogram in 200uu bins
    hist = Counter()
    for d in walk_dists:
        hist[int(d // 200) * 200] += 1

    return {
        "map": os.path.basename(path),
        "nav_node_count": len(nav_locs),
        "pickup_count": len(pickups),
        "map_radius": round(map_radius, 1),
        "z_min": round(z_min, 1), "z_max": round(z_max, 1),
        "floor_bands": n_floors,
        "floor_node_counts": {int(k): v for k, v in sorted(floor_node_counts.items())},
        "centroid": [round(cx, 1), round(cy, 1), round(cz, 1)],
        "walk_gap": cat_stats(walk_dists),
        "walk_gap_hist_200uu": {int(k): v for k, v in sorted(hist.items())},
        "invspot_out_degree": cat_stats(spot_degrees),
        "invspot_isolated_lt2": iso_spots,
        "by_category": cat_summary,
        "pickups": pickups,
    }


# --------------------------------------------------------------------------- #
# Cross-map aggregation + report
# --------------------------------------------------------------------------- #
def _agg(values):
    if not values:
        return None
    s = sorted(values)
    import statistics as st
    return {
        "n": len(s), "min": round(s[0], 1),
        "median": round(st.median(s), 1), "max": round(s[-1], 1),
        "mean": round(st.fmean(s), 1),
        "p25": round(_pct(s, 0.25), 1), "p75": round(_pct(s, 0.75), 1),
        "p90": round(_pct(s, 0.90), 1),
    }


def cross_map(results) -> dict:
    results = [r for r in results if "error" not in r]
    # pool every pickup across every map, per category, for each metric
    pool = defaultdict(lambda: defaultdict(list))
    premium = defaultdict(lambda: defaultdict(list))
    all_walk = []
    spot_degrees = []
    iso_total = 0
    floor_density = []     # nodes per floor band, pooled
    for r in results:
        for p in r["pickups"]:
            c = p["category"]
            for m in ("z_above_spot", "nearest_nav_dist", "nearest_wall_dist",
                      "nearest_pickup_dist", "nearest_same_cat_dist",
                      "nearest_spawn_dist", "centrality", "elev_norm"):
                if p.get(m) is not None:
                    pool[c][m].append(p[m])
            if p.get("weapon_type") in PREMIUM_WEAPONS:
                for m in ("centrality", "elev_norm", "nearest_spawn_dist",
                          "nearest_wall_dist"):
                    if p.get(m) is not None:
                        premium[p["weapon_type"]][m].append(p[m])
        if r["walk_gap"]:
            # reconstruct pooled walk dists from histogram-ish: use per-map stats
            pass
        if r.get("invspot_out_degree"):
            spot_degrees.append(r["invspot_out_degree"]["mean"])
        iso_total += r.get("invspot_isolated_lt2", 0)
        for cnt in r["floor_node_counts"].values():
            floor_density.append(cnt)

    pooled = {c: {m: _agg(v) for m, v in metrics.items()}
              for c, metrics in pool.items()}
    premium_pooled = {w: {m: _agg(v) for m, v in metrics.items()}
                      for w, metrics in premium.items()}

    # weapon-type distribution
    wt = Counter()
    for r in results:
        for p in r["pickups"]:
            if p.get("weapon_type"):
                wt[p["weapon_type"]] += 1

    return {
        "n_maps": len(results),
        "pooled_by_category": pooled,
        "premium_weapons": premium_pooled,
        "weapon_type_counts": dict(wt.most_common()),
        "invspot_mean_out_degree": _agg(spot_degrees),
        "invspot_isolated_total": iso_total,
        "floor_band_node_count": _agg(floor_density),
        "walk_gap_max_per_map": _agg([r["walk_gap"]["max"] for r in results
                                      if r["walk_gap"]]),
        "walk_gap_median_per_map": _agg([r["walk_gap"]["median"] for r in results
                                         if r["walk_gap"]]),
        "walk_gap_p90_per_map": _agg([r["walk_gap"]["p90"] for r in results
                                      if r["walk_gap"]]),
    }


def print_report(results, agg):
    def row(label, st):
        if not st:
            print(f"    {label:20s} (no data)")
            return
        print(f"    {label:20s} n={st['n']:5d}  min={st['min']:8.1f}  "
              f"p25={st['p25']:8.1f}  med={st['median']:8.1f}  "
              f"p75={st['p75']:8.1f}  p90={st['p90']:8.1f}  max={st['max']:8.1f}")

    print("=" * 78)
    print(f"PICKUP COORDINATE SURVEY  ({agg['n_maps']} maps)")
    print("=" * 78)

    order = ["ammo", "health", "adrenaline", "weapon", "armor", "powerup",
             "pickup-other"]
    cats = [c for c in order if c in agg["pooled_by_category"]]
    cats += [c for c in agg["pooled_by_category"] if c not in cats]

    print("\n-- Pickup placement vs geometry (pooled over all maps, all pickups) --")
    for c in cats:
        m = agg["pooled_by_category"][c]
        print(f"\n  [{c}]")
        row("z_above_spot(uu)", m.get("z_above_spot"))
        row("dist_nearest_nav", m.get("nearest_nav_dist"))
        row("dist_nearest_wall", m.get("nearest_wall_dist"))
        row("dist_nearest_pickup", m.get("nearest_pickup_dist"))
        row("dist_same_category", m.get("nearest_same_cat_dist"))
        row("dist_nearest_spawn", m.get("nearest_spawn_dist"))
        row("centrality[0..1]", m.get("centrality"))
        row("elev_norm[0..1]", m.get("elev_norm"))

    print("\n-- HIGH-VALUE anchoring (centrality 0=centre/1=edge, elev 0=floor/1=top) --")
    for c in ("weapon", "armor", "powerup"):
        m = agg["pooled_by_category"].get(c)
        if not m:
            continue
        cen, el = m.get("centrality"), m.get("elev_norm")
        sp = m.get("nearest_spawn_dist")
        print(f"  {c:10s}  centrality med={cen['median'] if cen else 0:.2f}  "
              f"elev med={el['median'] if el else 0:.2f}  "
              f"dist_to_spawn med={sp['median'] if sp else 0:.0f}uu")

    print("\n-- PREMIUM weapon placement (the reward-gating targets) --")
    print(f"  weapon-type counts: {agg['weapon_type_counts']}")
    for w, m in agg["premium_weapons"].items():
        cen, el = m.get("centrality"), m.get("elev_norm")
        sp, wl = m.get("nearest_spawn_dist"), m.get("nearest_wall_dist")
        print(f"  {w:18s} n={cen['n'] if cen else 0:2d}  "
              f"centrality med={cen['median'] if cen else 0:.2f}  "
              f"elev med={el['median'] if el else 0:.2f}  "
              f"dist_spawn med={sp['median'] if sp else 0:.0f}  "
              f"dist_wall med={wl['median'] if wl else 0:.0f}")

    print("\n-- Nav-node spatial distribution --")
    fb = agg["floor_band_node_count"]
    print(f"  nodes per 256uu floor band: med={fb['median']:.0f} "
          f"(p25={fb['p25']:.0f} p75={fb['p75']:.0f} max={fb['max']:.0f})")
    od = agg["invspot_mean_out_degree"]
    print(f"  InventorySpot mean out-degree (per map): med={od['median']:.2f} "
          f"min={od['min']:.2f} max={od['max']:.2f}")
    print(f"  InventorySpots with out-degree <2 (isolated): {agg['invspot_isolated_total']}")

    print("\n-- Realised walk-gap distribution (per-map stats, then across maps) --")
    print(f"  per-map MAX walk-gap:    {agg['walk_gap_max_per_map']}")
    print(f"  per-map MEDIAN walk-gap: {agg['walk_gap_median_per_map']}")
    print(f"  per-map P90 walk-gap:    {agg['walk_gap_p90_per_map']}")


def main(argv):
    as_json = "--json" in argv
    out_path = None
    files = []
    skip_next = False
    for i, a in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if a == "-o":
            out_path = argv[i + 1] if i + 1 < len(argv) else None
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        files.append(a)
    # drop the generated test skeleton if globbed in (not a stock map)
    files = [f for f in files if "skeleton" not in os.path.basename(f).lower()]
    results = [analyze(f) for f in files]
    agg = cross_map(results)
    if as_json:
        import json
        payload = {"cross_map": agg, "per_map": results}
        text = json.dumps(payload, indent=2)
        if out_path:
            with open(out_path, "w") as fh:
                fh.write(text)
            print(f"wrote {out_path} ({len(results)} maps, "
                  f"{sum(len(r.get('pickups', [])) for r in results)} pickups)")
        else:
            print(text)
        return 0
    print_report(results, agg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
