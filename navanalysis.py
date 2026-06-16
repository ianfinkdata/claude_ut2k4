#!/usr/bin/env python3
"""Bot-path & inventory pattern analysis across the UT2004 DM map inventory.

Builds on ut2parser to mine repeatable structure from the stock maps:
 - the navigation graph (NavigationPoint nodes + ReachSpec edges, with reach-flag
   semantics) that the bot AI traverses
 - inventory/pickup placement and how it ties into the nav graph
 - cross-map patterns (densities, connectivity, jump/lift usage, spawn counts)

Run:  python navanalysis.py Maps/*.ut2          # full report
      python navanalysis.py Maps/DM-Rankin.ut2  # one map
      python navanalysis.py Maps/*.ut2 --json    # machine-readable
"""

from __future__ import annotations

import glob
import math
import os
import statistics
from collections import Counter, defaultdict

import ut2parser as u

# reachFlags bits (from Engine/ReachSpec.uc)
REACH_FLAGS = [
    (1, "walk"), (2, "fly"), (4, "swim"), (8, "jump"), (16, "door"),
    (32, "special"), (64, "ladder"), (128, "proscribed"), (256, "forced"),
    (512, "playeronly"),
]

# NavigationPoint subclasses (the bot graph nodes)
NAV_CLASSES = {
    "PathNode", "InventorySpot", "JumpSpot", "JumpDest", "PlayerStart",
    "LiftCenter", "LiftExit", "Teleporter", "WarpZoneMarker", "AIMarker",
    "AssaultPath", "FlagBase", "DomPoint", "ScriptedSequence", "PortalMarker",
    "TranslocDest", "RoadPathNode", "QueuePoint", "PathNodeSpecial",
}


def _classify_pickup(cls: str):
    """Return a coarse pickup category, or None if not a pickup."""
    c = cls.lower()
    if "adrenaline" in c:
        return "adrenaline"
    if "ammo" in c:
        return "ammo"
    if "weapon" in c and "base" in c:
        return "weapon"   # xWeaponBase = weapon spawn
    if "health" in c:
        return "health"
    if "shield" in c or "armor" in c:
        return "armor"
    if "udamage" in c or "damageamp" in c or "superhealth" in c or "powerup" in c:
        return "powerup"
    if "pickup" in c or "charger" in c:
        return "pickup-other"
    return None


def analyze(path: str) -> dict:
    pkg = u.parse(open(path, "rb").read(), os.path.splitext(os.path.basename(path))[0])
    nodes = {}       # export index -> {class, location, pathlist:[reachspec refs]}
    reachspecs = []  # decoded edges
    pickups = Counter()
    node_classes = Counter()
    rs_by_idx = {}

    for i, e in enumerate(pkg.exports):
        idx = i + 1
        if e.class_name == "ReachSpec":
            props = {p.name: p.value for p in u.read_properties(pkg, e)}
            rs = {
                "start": props.get("Start"),
                "end": props.get("End"),
                "dist": props.get("Distance", 0),
                "radius": props.get("CollisionRadius", 0),
                "height": props.get("CollisionHeight", 0),
                "flags": props.get("reachFlags", 0) or 0,
                "forced": bool(props.get("bForced", False)),
            }
            reachspecs.append(rs)
            rs_by_idx[idx] = rs
            continue
        cat = _classify_pickup(e.class_name)
        if cat:
            pickups[cat] += 1
        if e.class_name in NAV_CLASSES or any(
                p.name == "PathList" for p in u.read_properties(pkg, e)):
            props = {p.name: p for p in u.read_properties(pkg, e)}
            loc = props["Location"].value if "Location" in props else None
            pl = props["PathList"].value if "PathList" in props else []
            refs = [el.ref for el in pl if isinstance(el, u.ObjectRef)] \
                if isinstance(pl, list) else []
            node_data = {"class": e.class_name, "loc": loc, "pathlist": refs}
            if e.class_name in ("LiftCenter", "LiftExit"):
                lt = props.get("LiftTag")
                node_data["lift_tag"] = lt.value if lt else None
            nodes[idx] = node_data
            node_classes[e.class_name] += 1

    # ----- graph metrics -----
    out_deg = [len(n["pathlist"]) for n in nodes.values()]
    flag_counts = Counter()
    for rs in reachspecs:
        labels = [name for bit, name in REACH_FLAGS if rs["flags"] & bit]
        for la in labels:
            flag_counts[la] += 1
        if not labels:
            flag_counts["(none)"] += 1
    dists = [rs["dist"] for rs in reachspecs if rs["dist"]]
    radii = Counter(rs["radius"] for rs in reachspecs)
    heights = Counter(rs["height"] for rs in reachspecs)

    # bounding box of nav nodes -> nav density per million uu^2 (floor area proxy)
    locs = [n["loc"] for n in nodes.values() if n["loc"]]
    area = 0.0
    if len(locs) > 2:
        xs = [l[0] for l in locs]
        ys = [l[1] for l in locs]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))

    # Walk-only edge distance distribution (flag bit 1 = walk)
    walk_dists = sorted(rs["dist"] for rs in reachspecs if rs["flags"] & 1 and rs["dist"])
    walk_dist_median = statistics.median(walk_dists) if walk_dists else 0
    walk_dist_max = walk_dists[-1] if walk_dists else 0
    walk_over_1200 = sum(1 for d in walk_dists if d > 1200)

    # Verticality: Z range and estimated floor count (256uu buckets)
    zs = [l[2] for l in locs if l and len(l) >= 3]
    z_range = (max(zs) - min(zs)) if len(zs) > 1 else 0
    floor_count = len(set(int(z // 256) for z in zs)) if zs else 0

    # Lift network: group LiftCenter/LiftExit by LiftTag, compute height spans
    lift_map: dict = defaultdict(lambda: {"czs": [], "ezs": []})
    for n in nodes.values():
        if n["class"] not in ("LiftCenter", "LiftExit") or not n["loc"]:
            continue
        tag = n.get("lift_tag") or "_untagged"
        key = "czs" if n["class"] == "LiftCenter" else "ezs"
        lift_map[tag][key].append(n["loc"][2])
    lift_count = node_classes.get("LiftCenter", 0)
    lift_exit_count = node_classes.get("LiftExit", 0)
    lift_heights = [
        max(d["czs"] + d["ezs"]) - min(d["czs"] + d["ezs"])
        for d in lift_map.values() if d["czs"] and d["ezs"]
    ]

    return {
        "map": os.path.basename(path),
        "nav_nodes": len(nodes),
        "node_classes": dict(node_classes),
        "reachspecs": len(reachspecs),
        "avg_out_degree": (sum(out_deg) / len(out_deg)) if out_deg else 0,
        "max_out_degree": max(out_deg) if out_deg else 0,
        "flag_counts": dict(flag_counts),
        "forced_edges": sum(1 for rs in reachspecs if rs["forced"]),
        "jump_edges": flag_counts.get("jump", 0),
        "dist_min": min(dists) if dists else 0,
        "dist_avg": (sum(dists) / len(dists)) if dists else 0,
        "dist_max": max(dists) if dists else 0,
        "common_radius": radii.most_common(1)[0] if radii else (0, 0),
        "common_height": heights.most_common(1)[0] if heights else (0, 0),
        "pickups": dict(pickups),
        "playerstarts": node_classes.get("PlayerStart", 0),
        "inventoryspots": node_classes.get("InventorySpot", 0),
        "pickup_total": sum(pickups.values()),
        "nav_area": area,
        # walk-gap
        "walk_edge_count": len(walk_dists),
        "walk_dist_median": walk_dist_median,
        "walk_dist_max": walk_dist_max,
        "walk_over_1200": walk_over_1200,
        # verticality
        "z_range": z_range,
        "floor_count": floor_count,
        # lift network
        "lift_count": lift_count,
        "lift_exit_count": lift_exit_count,
        "avg_lift_height": (sum(lift_heights) / len(lift_heights)) if lift_heights else 0,
        "max_lift_height": max(lift_heights) if lift_heights else 0,
    }


def _bar(n, total, width=24):
    if not total:
        return ""
    return "#" * int(round(width * n / total))


def print_one(a: dict) -> None:
    print(f"\n== {a['map']} ==")
    print(f"  nav nodes: {a['nav_nodes']:4d}   reachspec edges: {a['reachspecs']:5d}"
          f"   avg out-degree: {a['avg_out_degree']:.1f} (max {a['max_out_degree']})")
    print("  node types: " + ", ".join(f"{k}={v}" for k, v in
          sorted(a["node_classes"].items(), key=lambda x: -x[1])))
    print(f"  edge reach-flags: " + ", ".join(f"{k}={v}" for k, v in
          sorted(a["flag_counts"].items(), key=lambda x: -x[1])))
    print(f"  jump edges: {a['jump_edges']}   forced(bForced): {a['forced_edges']}"
          f"   edge dist avg/max: {a['dist_avg']:.0f}/{a['dist_max']}")
    print(f"  path collision size (most common): radius={a['common_radius'][0]}"
          f" height={a['common_height'][0]}")
    print(f"  spawns(PlayerStart): {a['playerstarts']}   InventorySpots:"
          f" {a['inventoryspots']}   pickups: {a['pickup_total']} {a['pickups']}")
    print(f"  walk gaps: {a['walk_edge_count']} edges  median={a['walk_dist_median']:.0f}"
          f"  max={a['walk_dist_max']:.0f}  over-1200uu: {a['walk_over_1200']}")
    print(f"  verticality: Z-range={a['z_range']:.0f}  floors~{a['floor_count']}"
          f"   lifts: {a['lift_count']} (exits={a['lift_exit_count']}"
          f"  avg_h={a['avg_lift_height']:.0f}  max_h={a['max_lift_height']:.0f})")


def print_summary(results: list) -> None:
    print("\n" + "=" * 70)
    print("CROSS-MAP PATTERNS (%d maps)" % len(results))
    print("=" * 70)

    def avg(key):
        vs = [r[key] for r in results]
        return sum(vs) / len(vs)

    print(f"avg nav nodes/map: {avg('nav_nodes'):.0f}    "
          f"avg reachspecs/map: {avg('reachspecs'):.0f}    "
          f"avg out-degree: {avg('avg_out_degree'):.1f}")
    print(f"avg spawns: {avg('playerstarts'):.1f}    "
          f"avg InventorySpots: {avg('inventoryspots'):.1f}    "
          f"avg pickups: {avg('pickup_total'):.1f}")

    # InventorySpot vs pickup correlation (is it ~1:1?)
    pairs = [(r["inventoryspots"], r["pickup_total"]) for r in results
             if r["pickup_total"]]
    ratio = sum(a / b for a, b in pairs) / len(pairs) if pairs else 0
    print(f"\nInventorySpot : pickup ratio (avg): {ratio:.2f}  "
          f"-> {'~1 nav node per pickup' if 0.8 < ratio < 1.2 else 'varies'}")

    # global reach-flag mix
    gflags = Counter()
    for r in results:
        for k, v in r["flag_counts"].items():
            gflags[k] += v
    tot = sum(gflags.values())
    print(f"\nGlobal edge-type mix ({tot} edges across all maps):")
    for k, v in gflags.most_common():
        print(f"  {k:12s} {v:6d}  {100*v//tot:3d}%  {_bar(v, tot)}")

    # collision size — the bot the paths are cut for
    rc = Counter(r["common_radius"][0] for r in results)
    hc = Counter(r["common_height"][0] for r in results)
    print(f"\nDominant path collision size: radius {rc.most_common(1)[0][0]} "
          f"(in {rc.most_common(1)[0][1]}/{len(results)} maps), "
          f"height {hc.most_common(1)[0][0]} "
          f"(in {hc.most_common(1)[0][1]}/{len(results)} maps)")

    # pickup category totals
    pcat = Counter()
    for r in results:
        for k, v in r["pickups"].items():
            pcat[k] += v
    print(f"\nPickup category totals: " + ", ".join(f"{k}={v}" for k, v in
          pcat.most_common()))

    def _stats(key):
        vs = sorted(r[key] for r in results)
        return vs[0], statistics.median(vs), vs[-1]

    # Walk-gap distribution
    wmin, wmed, wmax = _stats("walk_dist_max")
    over = sum(r["walk_over_1200"] for r in results)
    total_walk = sum(r["walk_edge_count"] for r in results)
    print(f"\nWalk-only edge max-gap  min={wmin:.0f}  median={wmed:.0f}  max={wmax:.0f} uu")
    print(f"  walk edges over 1200uu: {over}/{total_walk} ({100*over//total_walk if total_walk else 0}%)")
    wmed_med = statistics.median(r["walk_dist_median"] for r in results)
    print(f"  median walk-gap (per-map median, then median across maps): {wmed_med:.0f} uu")

    # Verticality
    zmin, zmed, zmax = _stats("z_range")
    fmin, fmed, fmax = _stats("floor_count")
    print(f"\nVerticality  Z-range: min={zmin:.0f}  median={zmed:.0f}  max={zmax:.0f} uu")
    print(f"  Floor count (256uu buckets): min={fmin}  median={fmed}  max={fmax}")

    # Lift network
    lmin, lmed, lmax = _stats("lift_count")
    hmin, hmed, hmax = _stats("avg_lift_height")
    maps_with_lifts = sum(1 for r in results if r["lift_count"] > 0)
    print(f"\nLift network ({maps_with_lifts}/{len(results)} maps have lifts)")
    print(f"  lift count: min={lmin}  median={lmed}  max={lmax}")
    print(f"  avg lift height: min={hmin:.0f}  median={hmed:.0f}  max={hmax:.0f} uu")


def main(argv):
    files = [f for f in argv if not f.startswith("--")]
    as_json = "--json" in argv
    results = [analyze(f) for f in files]
    if as_json:
        import json
        print(json.dumps(results, indent=2))
        return 0
    for a in results:
        print_one(a)
    if len(results) > 1:
        print_summary(results)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
