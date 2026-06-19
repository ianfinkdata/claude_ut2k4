#!/usr/bin/env python3
"""mesh-browser query engine.

Inverts the per-map static-mesh data in surveys/meshes.json into a
mesh -> maps index and answers browse queries:

  - substring search across full ref / package / group / name
  - --package PKG     list meshes in a package
  - --role ROLE       fine role (door, window, trim, structural, pipe, light,
                      machine, container, debris, floor, deco, nature, ...)
  - --bucket BUCKET   coarse role: prop | structural | trim
  - --list-packages   package summary (map coverage + mesh/placement counts)
  - --list-roles      show available fine roles with counts

For each matching mesh it reports the PACKAGE, the mesh NAME (and group), its
role/bucket, a scale hint, and the EXAMPLE MAPS that use it, ranked by placement
count. stdlib only. See SKILL.md for usage patterns.
"""
import argparse
import json
import os
import sys


def find_data(explicit=None):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        sys.exit(f"--data path not found: {explicit}")
    starts = [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for start in starts:
        cur = start
        for _ in range(12):
            cand = os.path.join(cur, "surveys", "meshes.json")
            if os.path.isfile(cand):
                return cand
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    sys.exit("Could not find surveys/meshes.json. Run from inside the repo or pass "
             "--data <path>. Regenerate with: python surveys/mesh_survey.py --json -o surveys/meshes.json")


def map_label(name):
    return name[:-4] if name.lower().endswith(".ut2") else name


def build_index(data):
    """mesh ref -> aggregate record with per-map placement counts."""
    index = {}
    for m in data.get("maps", []):
        mapname = m.get("map", "?")
        for rec in m.get("meshes", []):
            ref = rec.get("mesh") or rec.get("name", "?")
            e = index.setdefault(ref, {
                "ref": ref, "pkg": rec.get("pkg", ""), "group": rec.get("group", ""),
                "name": rec.get("name", ref), "local": rec.get("local", False),
                "role": rec.get("role", ""), "bucket": rec.get("bucket", ""),
                "total": 0, "maps": [], "common_scale": rec.get("common_scale"),
                "nonuniform_pct": rec.get("nonuniform_pct", 0),
            })
            e["total"] += rec.get("count", 0)
            e["maps"].append({"map": map_label(mapname), "count": rec.get("count", 0)})
            # prefer scale info from the heaviest-use map
            if rec.get("count", 0) >= max((mm["count"] for mm in e["maps"]), default=0):
                e["common_scale"] = rec.get("common_scale", e["common_scale"])
                e["nonuniform_pct"] = rec.get("nonuniform_pct", e["nonuniform_pct"])
    for e in index.values():
        e["maps"].sort(key=lambda x: -x["count"])
    return index


def scale_hint(e):
    cs = e.get("common_scale")
    nu = e.get("nonuniform_pct", 0) or 0
    bits = []
    if cs and list(cs) != [1.0, 1.0, 1.0]:
        bits.append("common scale " + "x".join(str(round(v, 2)) for v in cs))
    elif cs:
        bits.append("usually 1:1 scale")
    if nu >= 25:
        bits.append(f"often stretched ({nu}% non-uniform)")
    return "; ".join(bits)


def match(e, term):
    t = term.lower()
    return any(t in str(e[k]).lower() for k in ("ref", "pkg", "group", "name"))


def print_entry(e, maps_limit):
    grp = f".{e['group']}" if e["group"] else ""
    tags = "/".join(x for x in (e["role"], e["bucket"]) if x)
    loc = "  (map-local)" if e.get("local") else ""
    print(f"\n{e['pkg']}{grp}.{e['name']}   [{tags}]{loc}")
    print(f"    package: {e['pkg']}   group: {e['group'] or '-'}   name: {e['name']}")
    nmaps = len(e["maps"])
    sh = scale_hint(e)
    print(f"    used in {nmaps} map(s), {e['total']} placement(s)" + (f"   [{sh}]" if sh else ""))
    shown = e["maps"][:maps_limit]
    ex = ", ".join(f"{mp['map']} ({mp['count']})" for mp in shown)
    more = f", +{nmaps - len(shown)} more" if nmaps > len(shown) else ""
    print(f"    example maps: {ex}{more}")


def cmd_list_packages(index, args):
    mesh_count, place_count, mapset = {}, {}, {}
    for e in index.values():
        p = e["pkg"]
        mesh_count[p] = mesh_count.get(p, 0) + 1
        place_count[p] = place_count.get(p, 0) + e["total"]
        mapset.setdefault(p, set()).update(mp["map"] for mp in e["maps"])
    pkgs = sorted(mesh_count, key=lambda p: -place_count.get(p, 0))
    print(f"{'PACKAGE':38s} {'MAPS':>5s} {'MESHES':>7s} {'PLACED':>7s}")
    for p in pkgs:
        if args.term and args.term.lower() not in p.lower():
            continue
        print(f"{p:38s} {len(mapset[p]):>5} {mesh_count[p]:>7} {place_count.get(p,0):>7}")


def cmd_list_roles(index):
    roles = {}
    for e in index.values():
        roles[e["role"]] = roles.get(e["role"], 0) + 1
    print("Fine roles (distinct meshes per role):")
    for r, c in sorted(roles.items(), key=lambda x: -x[1]):
        print(f"  {c:5d}  {r or '(none)'}")


def main():
    ap = argparse.ArgumentParser(description="Browse UT2004 stock-map static-mesh usage.")
    ap.add_argument("term", nargs="?", help="substring to search (ref/package/group/name)")
    ap.add_argument("--package", help="restrict to one package (exact, case-insensitive)")
    ap.add_argument("--role", help="fine role exact match (e.g. door, window, trim, pipe, machine)")
    ap.add_argument("--bucket", choices=["prop", "structural", "trim"], help="coarse role")
    ap.add_argument("--list-packages", action="store_true")
    ap.add_argument("--list-roles", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--maps-limit", type=int, default=6)
    ap.add_argument("--include-local", action="store_true",
                    help="include map-local baked meshes (excluded by default — they won't resolve in other maps)")
    ap.add_argument("--data", help="path to meshes.json (default: auto-find surveys/meshes.json)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = json.load(open(find_data(args.data), encoding="utf-8"))
    index = build_index(data)

    if args.list_roles:
        cmd_list_roles(index)
        return
    if args.list_packages:
        cmd_list_packages(index, args)
        return

    results = list(index.values())
    if not args.include_local:
        results = [e for e in results if not e.get("local")]
    if args.package:
        results = [e for e in results if e["pkg"].lower() == args.package.lower()]
    if args.role:
        results = [e for e in results if e["role"].lower() == args.role.lower()]
    if args.bucket:
        results = [e for e in results if e["bucket"] == args.bucket]
    if args.term:
        results = [e for e in results if match(e, args.term)]

    results.sort(key=lambda e: -e["total"])

    if args.json:
        print(json.dumps(results[:args.limit], indent=2))
        return

    if not results:
        print("No meshes matched. Try a broader term, --list-roles, or --list-packages.")
        return
    print(f"{len(results)} mesh(es) matched"
          + (f"; showing top {args.limit}" if len(results) > args.limit else "") + ":")
    for e in results[:args.limit]:
        print_entry(e, args.maps_limit)


if __name__ == "__main__":
    main()
