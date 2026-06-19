#!/usr/bin/env python3
"""StaticMesh usage survey across the UT2004 stock DM map inventory.

Built on ut2parser. Mines repeatable static-mesh placement structure from the
stock maps -- the raw material for a procedural generator's "dress the room"
pass:

 - which meshes are placed, how often, and from which source package/group
 - DrawScale / DrawScale3D distributions (uniform vs stretched-along-one-axis)
 - Rotation distributions (axis-aligned snapping vs free rotation)
 - source-package co-occurrence (which mesh sets ship together = a "theme set")
 - a derived ROLE per mesh (trim / prop / structural / light / pipe / ...),
   from the asset Group name + mesh-name keywords + scale signature.

Mesh-bearing actor classes surveyed: StaticMeshActor (the overwhelming
majority) plus xWeaponBase / HealthCharger / Mover / KActor / MeshEmitter,
which also carry a StaticMesh property.

Run:  python surveys/mesh_survey.py Maps/DM-*.ut2          # full report
      python surveys/mesh_survey.py Maps/DM-Rankin.ut2     # one map
      python surveys/mesh_survey.py Maps/DM-*.ut2 --json   # machine-readable

stdlib only; imports ut2parser from the repo root.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from collections import Counter, defaultdict

# allow running from repo root or from surveys/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut2parser as u  # noqa: E402

# Actor classes that carry a StaticMesh property (verified across all 39 maps).
MESH_ACTOR_CLASSES = {
    "StaticMeshActor", "xWeaponBase", "HealthCharger", "SuperHealthCharger",
    "Mover", "ClientMover", "KActor", "MeshEmitter",
}

# Rotation is stored in Unreal units: 65536 == 360 degrees.
URU = 65536


# --------------------------------------------------------------------------- #
# Role classification
# --------------------------------------------------------------------------- #
# Order matters: first matching rule wins. Keys are matched (case-insensitive,
# substring) against BOTH the asset Group name and the mesh name.
_ROLE_KEYWORDS = [
    ("light",      ("light", "lamp", "licht", "spotlight", "lumi", "glow",
                    "neon", "fluoro")),
    ("pipe",       ("pipe", "rohr", "duct", "vent", "conduit", "tube",
                    "cable", "wire", "hose")),
    ("structural", ("pillar", "column", "girder", "beam", "brace", "support",
                    "truss", "frame", "balken", "traeger", "gurder", "girder",
                    "strut", "arch", "buttress")),
    ("wall",       ("wall", "panel", "wandeel", "wand", "facade", "bulkhead",
                    "partition")),
    ("ceiling",    ("ceiling", "cieling", "roof", "plafond", "soffit")),
    ("floor",      ("floor", "grate", "grating", "catwalk", "walkway", "ramp",
                    "stair", "step", "plank", "ground", "platform", "deck")),
    ("door",       ("door", "doorway", "gate", "hatch", "portal", "shutter")),
    ("trim",       ("trim", "edge", "molding", "border", "rim", "fillet",
                    "corner", "kosijn", "frame", "rand")),
    ("window",     ("window", "raam", "glass", "pane", "skylight")),
    ("rail",       ("rail", "fence", "barrier", "handrail", "guard", "banister")),
    ("machine",    ("machine", "engine", "turbine", "generator", "reactor",
                    "tank", "valve", "console", "panel_control", "computer",
                    "screen", "monitor", "gear", "piston", "fan", "rotor",
                    "mech", "tech", "device", "terminal")),
    ("container",  ("barrel", "crate", "box", "container", "drum", "cask",
                    "canister", "tank2")),
    ("debris",     ("rubble", "debris", "junk", "scrap", "wreck", "rust",
                    "broken", "rock", "stone", "boulder")),
    ("nature",     ("tree", "plant", "vine", "grass", "bush", "leaf", "branch",
                    "boom", "foliage", "coral", "fungus")),
    ("deco",       ("deko", "deco", "detail", "misc", "prop", "ornament",
                    "statue", "banner", "sign", "logo", "decal3d")),
    ("sky",        ("sky", "skyline", "skysheet", "cloud", "backdrop",
                    "distant")),
]

# A coarse 3-way bucket the generator cares about most (per task spec):
#   trim       -> edge dressing along a surface (trim/wall/ceiling/window/rail/light/pipe deco)
#   structural -> load-bearing / room-defining geometry (pillar/beam/door/floor/structural)
#   prop       -> freestanding object in the room volume (machine/container/debris/nature/deco)
_ROLE_TO_BUCKET = {
    "trim": "trim", "wall": "trim", "ceiling": "trim", "window": "trim",
    "rail": "trim", "light": "trim", "pipe": "trim",
    "structural": "structural", "door": "structural", "floor": "structural",
    "machine": "prop", "container": "prop", "debris": "prop",
    "nature": "prop", "deco": "prop", "sky": "prop", "other": "prop",
}


def split_ref(q: str):
    """Split a qualified ref Class'Pkg.Group.Name' into (pkg, group, name).

    2-segment refs (Pkg.Name) have no group -> group is ''.  Returns
    (pkg, group, name); any of these may be '' if unresolvable."""
    if "'" in q:
        inner = q.split("'", 2)[1]
    else:
        inner = q
    parts = [p for p in inner.split(".") if p]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) == 1:
        return "", "", parts[0]
    return "", "", ""


def classify_role(group: str, name: str, scale3d) -> str:
    """Derive a fine-grained role from the asset Group + mesh name, with a
    scale-signature fallback for ambiguous names."""
    hay = (group + " " + name).lower()
    for role, keys in _ROLE_KEYWORDS:
        for k in keys:
            if k in hay:
                return role
    # scale-signature fallback: a mesh stretched hard on one axis is usually a
    # beam/trim run; a flat wide mesh is a panel; otherwise unknown prop.
    if scale3d and len(scale3d) == 3:
        sx, sy, sz = scale3d
        mx, mn = max(sx, sy, sz), min(sx, sy, sz)
        if mn > 0 and mx / mn >= 3.0:
            return "structural"  # long thin -> beam/trim/pipe run
    return "other"


def role_bucket(role: str) -> str:
    return _ROLE_TO_BUCKET.get(role, "prop")


# --------------------------------------------------------------------------- #
# Per-map analysis
# --------------------------------------------------------------------------- #
def _as_scale3d(props) -> tuple:
    """Combine DrawScale (scalar) and DrawScale3D (vector) into an effective
    (x,y,z) scale. Engine multiplies them; defaults are 1.0."""
    ds = props.get("DrawScale")
    ds3 = props.get("DrawScale3D")
    if isinstance(ds3, tuple) and len(ds3) == 3:
        base = list(ds3)
    elif isinstance(ds3, list) and len(ds3) == 3:
        base = list(ds3)
    else:
        base = [1.0, 1.0, 1.0]
    if isinstance(ds, (int, float)):
        base = [c * ds for c in base]
    return tuple(round(c, 4) for c in base)


def _rot_snap(yaw: int) -> bool:
    """True if a yaw is snapped to a 90-degree (16384 uu) increment, within a
    small tolerance (the editor's grid snapping)."""
    if yaw is None:
        return False
    q = URU // 4  # 16384 == 90 deg
    r = yaw % q
    return r <= 64 or r >= q - 64


def analyze(path: str) -> dict:
    pkg = u.parse(open(path, "rb").read(),
                  os.path.splitext(os.path.basename(path))[0])

    # mesh -> usage record
    mesh_rec = defaultdict(lambda: {
        "count": 0, "pkg": "", "group": "", "name": "", "role": "",
        "bucket": "", "scales": [], "yaws": [], "pitches": [], "rolls": [],
        "by_class": Counter(), "local": False,
    })
    pkg_counts = Counter()      # source package -> mesh-actor count
    pkg_meshes = defaultdict(set)
    role_counts = Counter()
    bucket_counts = Counter()
    class_counts = Counter()
    unresolved = 0
    total_actors = 0

    for e in pkg.exports:
        if e.class_name not in MESH_ACTOR_CLASSES:
            continue
        props = {p.name: p.value for p in u.read_properties(pkg, e)}
        mref = props.get("StaticMesh")
        if not isinstance(mref, u.ObjectRef) or mref.ref == 0:
            continue
        q = mref.qualified()
        if q == "None" or "<" in q:
            unresolved += 1
            continue
        total_actors += 1
        class_counts[e.class_name] += 1
        src_pkg, group, name = split_ref(q)
        local = (src_pkg == pkg.package_name)
        key = q.split("'", 2)[1] if "'" in q else q  # Pkg.Group.Name

        scale3d = _as_scale3d(props)
        rot = props.get("Rotation")
        yaw = pitch = roll = None
        if isinstance(rot, dict):
            yaw, pitch, roll = rot.get("yaw"), rot.get("pitch"), rot.get("roll")

        rec = mesh_rec[key]
        rec["count"] += 1
        rec["pkg"] = src_pkg
        rec["group"] = group
        rec["name"] = name
        rec["local"] = local
        rec["scales"].append(scale3d)
        rec["by_class"][e.class_name] += 1
        if yaw is not None:
            rec["yaws"].append(yaw)
        if pitch:
            rec["pitches"].append(pitch)
        if roll:
            rec["rolls"].append(roll)
        if not rec["role"]:
            rec["role"] = classify_role(group, name, scale3d)
            rec["bucket"] = role_bucket(rec["role"])

        pkg_counts[src_pkg] += 1
        pkg_meshes[src_pkg].add(key)

    # finalize per-mesh stats
    meshes = []
    for key, rec in mesh_rec.items():
        role_counts[rec["role"]] += rec["count"]
        bucket_counts[rec["bucket"]] += rec["count"]
        scales = rec["scales"]
        # uniform vs non-uniform scaling
        n_scaled = sum(1 for s in scales if s != (1.0, 1.0, 1.0))
        n_nonuniform = sum(1 for s in scales
                           if len(set(s)) > 1)
        yaws = rec["yaws"]
        n_snapped = sum(1 for y in yaws if _rot_snap(y))
        meshes.append({
            "mesh": key,
            "pkg": rec["pkg"],
            "group": rec["group"],
            "name": rec["name"],
            "local": rec["local"],
            "role": rec["role"],
            "bucket": rec["bucket"],
            "count": rec["count"],
            "by_class": dict(rec["by_class"]),
            "scaled_pct": round(100 * n_scaled / len(scales)) if scales else 0,
            "nonuniform_pct": round(100 * n_nonuniform / len(scales)) if scales else 0,
            "common_scale": Counter(scales).most_common(1)[0][0] if scales else (1, 1, 1),
            "yaw_snapped_pct": round(100 * n_snapped / len(yaws)) if yaws else 0,
            "tilted_pct": round(100 * len(rec["pitches"]) / rec["count"]) if rec["count"] else 0,
        })
    meshes.sort(key=lambda m: -m["count"])

    return {
        "map": os.path.basename(path),
        "mesh_actor_total": total_actors,
        "distinct_meshes": len(meshes),
        "unresolved_refs": unresolved,
        "class_counts": dict(class_counts),
        "role_counts": dict(role_counts),
        "bucket_counts": dict(bucket_counts),
        "source_packages": dict(pkg_counts.most_common()),
        "meshes": meshes,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _bar(n, total, width=24):
    if not total:
        return ""
    return "#" * int(round(width * n / total))


def print_one(a: dict) -> None:
    print(f"\n== {a['map']} ==")
    print(f"  mesh actors: {a['mesh_actor_total']}   distinct meshes:"
          f" {a['distinct_meshes']}   unresolved refs: {a['unresolved_refs']}")
    print("  actor classes: " + ", ".join(f"{k}={v}" for k, v in
          sorted(a["class_counts"].items(), key=lambda x: -x[1])))
    print("  role mix: " + ", ".join(f"{k}={v}" for k, v in
          sorted(a["role_counts"].items(), key=lambda x: -x[1])))
    print("  bucket mix: " + ", ".join(f"{k}={v}" for k, v in
          sorted(a["bucket_counts"].items(), key=lambda x: -x[1])))
    top_pkgs = list(a["source_packages"].items())[:5]
    print("  top source pkgs: " + ", ".join(f"{k}={v}" for k, v in top_pkgs))
    print("  top meshes:")
    for m in a["meshes"][:8]:
        loc = " (local)" if m["local"] else ""
        print(f"    {m['count']:4d}  [{m['bucket']:10s}/{m['role']:10s}]"
              f" {m['mesh']}{loc}  scale={m['common_scale']}"
              f" nonuniform={m['nonuniform_pct']}% yawsnap={m['yaw_snapped_pct']}%")


def print_summary(results: list) -> None:
    print("\n" + "=" * 72)
    print("CROSS-MAP STATIC-MESH PATTERNS (%d maps)" % len(results))
    print("=" * 72)

    def avg(key):
        vs = [r[key] for r in results]
        return sum(vs) / len(vs)

    print(f"avg mesh actors/map: {avg('mesh_actor_total'):.0f}    "
          f"avg distinct meshes/map: {avg('distinct_meshes'):.0f}")

    # global role / bucket mix
    groles = Counter()
    gbuckets = Counter()
    for r in results:
        for k, v in r["role_counts"].items():
            groles[k] += v
        for k, v in r["bucket_counts"].items():
            gbuckets[k] += v
    tot = sum(groles.values())
    print(f"\nGlobal ROLE mix ({tot} placements):")
    for k, v in groles.most_common():
        print(f"  {k:12s} {v:7d}  {100*v//tot:3d}%  {_bar(v, tot)}")
    totb = sum(gbuckets.values())
    print(f"\nGlobal BUCKET mix ({totb} placements):")
    for k, v in gbuckets.most_common():
        print(f"  {k:12s} {v:7d}  {100*v//totb:3d}%  {_bar(v, totb)}")

    # source-package frequency (how many maps use each pkg, and total placements)
    pkg_maps = Counter()
    pkg_total = Counter()
    for r in results:
        for k, v in r["source_packages"].items():
            pkg_total[k] += v
            pkg_maps[k] += 1
    print(f"\nTop source packages (placements / #maps using):")
    for k, v in pkg_total.most_common(20):
        flag = " [map-local re-export]" if pkg_maps[k] == 1 and any(
            k == r["map"].rsplit(".", 1)[0] for r in results) else ""
        print(f"  {v:7d}  in {pkg_maps[k]:2d} maps  {k}{flag}")

    # package CO-OCCURRENCE: which external pkgs ship together
    stock_local = {r["map"].rsplit(".", 1)[0] for r in results}
    cooc = Counter()
    for r in results:
        ext = sorted(p for p in r["source_packages"]
                     if p not in stock_local and p)
        for i in range(len(ext)):
            for j in range(i + 1, len(ext)):
                cooc[(ext[i], ext[j])] += 1
    print(f"\nTop external-package CO-OCCURRENCE (used together in N maps):")
    for (a, b), n in cooc.most_common(15):
        print(f"  {n:2d}  {a}  +  {b}")

    # scale / rotation conventions
    all_meshes = [m for r in results for m in r["meshes"]]
    nonuni = [m["nonuniform_pct"] for m in all_meshes]
    snapped = [m["yaw_snapped_pct"] for m in all_meshes if m["yaw_snapped_pct"] is not None]
    print(f"\nPlacement conventions (per-mesh medians across "
          f"{len(all_meshes)} mesh records):")
    print(f"  non-uniform DrawScale3D: median {statistics.median(nonuni):.0f}% "
          f"of placements per mesh")
    print(f"  yaw snapped to 90deg:    median {statistics.median(snapped):.0f}% "
          f"of placements per mesh")

    # most common meshes globally (by total placements, merging across maps)
    gm = Counter()
    gm_role = {}
    for m in all_meshes:
        gm[m["mesh"]] += m["count"]
        gm_role[m["mesh"]] = (m["bucket"], m["role"])
    print(f"\nMost-placed individual meshes (across all maps):")
    for mesh, n in gm.most_common(20):
        b, role = gm_role[mesh]
        print(f"  {n:5d}  [{b}/{role}]  {mesh}")


def main(argv):
    files = [f for f in argv if not f.startswith("--")]
    as_json = "--json" in argv
    results = [analyze(f) for f in files]
    if as_json:
        import json
        print(json.dumps({"maps": results}, indent=2))
        return 0
    for a in results:
        print_one(a)
    if len(results) > 1:
        print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
