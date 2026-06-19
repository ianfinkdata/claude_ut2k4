#!/usr/bin/env python3
"""texture-browser query engine.

Inverts the per-map texture data in surveys/textures.json into a
texture -> maps index and answers browse queries:

  - substring search across full ref / package / group / name
  - --package PKG     list textures in a package
  - --role ROLE       textures whose dominant surface role is wall/floor/ceiling
  - --list-packages   package summary (map coverage + texture count)

For each matching texture it reports the texture PACKAGE, the texture
NAME (and group), and the EXAMPLE MAPS that use it, ranked by how many
brush polygons in that map carry the texture (a proxy for prominence).

stdlib only. See SKILL.md for usage patterns.
"""
import argparse
import json
import os
import sys


def find_data(explicit=None):
    """Locate surveys/textures.json: explicit path, then walk up from CWD,
    then walk up from this script's location."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        sys.exit(f"--data path not found: {explicit}")
    starts = [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for start in starts:
        cur = start
        for _ in range(12):
            cand = os.path.join(cur, "surveys", "textures.json")
            if os.path.isfile(cand):
                return cand
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    sys.exit(
        "Could not find surveys/textures.json. Run from inside the repo, "
        "or pass --data <path>. Regenerate it with: python surveys/texture_survey.py --json"
    )


def map_label(name):
    """'DM-1on1-Albatross.ut2' -> 'DM-1on1-Albatross'."""
    return name[:-4] if name.lower().endswith(".ut2") else name


def split_ref(ref, catalog):
    """Return (package, group, name) for a fully-qualified texture ref,
    preferring the map's material_catalog metadata when present."""
    meta = catalog.get(ref)
    if meta:
        return meta.get("package", ""), meta.get("group", ""), meta.get("name", ref)
    parts = ref.split(".")
    if len(parts) >= 3:
        return parts[0], ".".join(parts[1:-1]), parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return "", "", ref


def build_index(data):
    """texture ref -> {package, group, name, total_polys, maps:[{map,polys,roles}]}."""
    index = {}
    for m in data.get("maps", []):
        mapname = m.get("map", "?")
        catalog = m.get("material_catalog", {}) or {}
        poly_totals = m.get("texture_poly_totals", {}) or {}
        roles = m.get("texture_role", {}) or {}
        for ref, polys in poly_totals.items():
            pkg, grp, nm = split_ref(ref, catalog)
            entry = index.setdefault(
                ref,
                {"ref": ref, "package": pkg, "group": grp, "name": nm,
                 "total_polys": 0, "maps": []},
            )
            entry["total_polys"] += polys
            entry["maps"].append({
                "map": map_label(mapname),
                "polys": polys,
                "roles": roles.get(ref, {}),
            })
    for entry in index.values():
        entry["maps"].sort(key=lambda x: -x["polys"])
    return index


def dominant_role(entry):
    agg = {}
    for mp in entry["maps"]:
        for r, c in (mp["roles"] or {}).items():
            agg[r] = agg.get(r, 0) + c
    if not agg:
        return None
    return max(agg, key=agg.get)


def match(entry, term):
    t = term.lower()
    return (t in entry["ref"].lower()
            or t in entry["package"].lower()
            or t in entry["group"].lower()
            or t in entry["name"].lower())


def print_entry(entry, maps_limit):
    role = dominant_role(entry)
    role_str = f"  [{role}]" if role else ""
    grp = f".{entry['group']}" if entry["group"] else ""
    print(f"\n{entry['package']}{grp}.{entry['name']}{role_str}")
    print(f"    package: {entry['package']}   group: {entry['group'] or '-'}   name: {entry['name']}")
    nmaps = len(entry["maps"])
    print(f"    used in {nmaps} map(s), {entry['total_polys']} polys total")
    shown = entry["maps"][:maps_limit]
    examples = ", ".join(f"{mp['map']} ({mp['polys']})" for mp in shown)
    more = f", +{nmaps - len(shown)} more" if nmaps > len(shown) else ""
    print(f"    example maps: {examples}{more}")


def cmd_list_packages(data, index, args):
    cov = data.get("cross_map", {}).get("package_map_coverage", {}) or {}
    tex_count, poly_count = {}, {}
    for e in index.values():
        tex_count[e["package"]] = tex_count.get(e["package"], 0) + 1
        poly_count[e["package"]] = poly_count.get(e["package"], 0) + e["total_polys"]
    pkgs = sorted(tex_count, key=lambda p: -poly_count.get(p, 0))
    print(f"{'PACKAGE':40s} {'MAPS':>5s} {'TEXTURES':>9s} {'POLYS':>9s}")
    for p in pkgs:
        if args.term and args.term.lower() not in p.lower():
            continue
        print(f"{p:40s} {cov.get(p, '?'):>5} {tex_count[p]:>9} {poly_count.get(p,0):>9}")


def main():
    ap = argparse.ArgumentParser(description="Browse UT2004 stock-map texture usage.")
    ap.add_argument("term", nargs="?", help="substring to search (ref/package/group/name)")
    ap.add_argument("--package", help="restrict to one package (exact, case-insensitive)")
    ap.add_argument("--role", choices=["wall", "floor", "ceiling"],
                    help="only textures whose dominant role is this")
    ap.add_argument("--list-packages", action="store_true",
                    help="summarize packages instead of textures")
    ap.add_argument("--limit", type=int, default=40, help="max textures shown (default 40)")
    ap.add_argument("--maps-limit", type=int, default=6, help="max example maps per texture (default 6)")
    ap.add_argument("--data", help="path to textures.json (default: auto-find surveys/textures.json)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()

    data = json.load(open(find_data(args.data), encoding="utf-8"))
    index = build_index(data)

    if args.list_packages:
        cmd_list_packages(data, index, args)
        return

    results = list(index.values())
    if args.package:
        results = [e for e in results if e["package"].lower() == args.package.lower()]
    if args.term:
        results = [e for e in results if match(e, args.term)]
    if args.role:
        results = [e for e in results if dominant_role(e) == args.role]

    results.sort(key=lambda e: -e["total_polys"])

    if args.json:
        out = [dict(e, dominant_role=dominant_role(e)) for e in results[:args.limit]]
        print(json.dumps(out, indent=2))
        return

    if not results:
        print("No textures matched. Try a broader term, or --list-packages.")
        return
    print(f"{len(results)} texture(s) matched"
          + (f"; showing top {args.limit}" if len(results) > args.limit else "") + ":")
    for e in results[:args.limit]:
        print_entry(e, args.maps_limit)


if __name__ == "__main__":
    main()
