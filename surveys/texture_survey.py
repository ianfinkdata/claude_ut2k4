#!/usr/bin/env python3
"""Texture / material / shader usage survey across the UT2004 DM map inventory.

Built on ut2parser, the same pattern as navanalysis.py: a re-runnable analysis
script that mines repeatable structure from the stock maps and feeds the
procedural generator (see PLAN_MONSTERBASE.md, Agent #1).

Two complementary signals are extracted per map:

 1. **Material catalog (import table).** Every Texture/Shader/Combiner/... the
    map references from other packages, with its dotted path
    `Package.Group.Name`. Tells us which art *packages* a map depends on.

 2. **Per-surface usage (brush polygons).** Every editor-brush polygon carries a
    Texture reference and a face normal. Classifying the normal into
    floor / wall / ceiling and counting the texture refs tells us not just
    *which* textures a map uses but *how much* and *on which surface role* --
    exactly the floor/wall/ceiling/trim split the generator needs to assign
    palettes to room-module surfaces.

Theme clustering groups maps by their dominant texture *packages* (the shared
art families), so the tech/industrial cluster (Rankin / Deck17 / Metallurgy
family) falls out of the package co-occurrence.

Run:  python surveys/texture_survey.py Maps/*.ut2          # full report
      python surveys/texture_survey.py Maps/DM-Rankin.ut2  # one map
      python surveys/texture_survey.py Maps/*.ut2 --json    # machine-readable
      python surveys/texture_survey.py Maps/*.ut2 --json > surveys/textures.json
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

# allow running from anywhere (repo root is the parent of surveys/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut2parser as u  # noqa: E402

# Import-table class names that denote a material/texture/shader resource.
# (Unreal Engine 2 material-tree node classes + the base bitmap/material.)
MATERIAL_CLASSES = {
    "Texture", "Shader", "Combiner", "TexOscillator", "TexPanner", "TexRotator",
    "FinalBlend", "Cubemap", "TexScaler", "ColorModifier", "TexEnvMap",
    "MaterialSequence", "VertexColor", "ConstantColor", "FadeColor",
    "TexCoordSource", "OpacityModifier", "TexModifier", "ProjectorMaterial",
    "BitmapMaterial", "Material", "Modifier", "MaterialSwitch",
}

# Texture packages that are not "architecture" surfaces -- skies, coronas,
# emitter/flare sprites, detail overlays, fog, HUD/engine defaults. Excluded
# from the architectural-palette ranking (they're not floor/wall/ceiling art).
NON_ARCH_PACKAGES = {
    "Engine", "Core", "EmitterTextures", "Coronas", "Flares", "DetailTextures",
    "CubeMaps", "skyeffects", "sky-goo", "skyline-epic", "skyline-meshes-epic",
    "ArboreaTerrain", "TowerTerrain", "AWGlobal", "UCGeneric",
}


def _qual_to_path(qref: str) -> str | None:
    """Texture'Pkg.Group.Name' -> 'Pkg.Group.Name' (None if not a ref)."""
    if "'" not in qref:
        return None
    inner = qref.split("'", 1)[1].rstrip("'")
    return inner or None


def _surface_role(normal: tuple) -> str:
    """Classify a polygon by its face normal: up-facing -> floor, down-facing
    -> ceiling, else wall. (UT2004 Z is up.)"""
    nz = normal[2] if len(normal) >= 3 else 0.0
    if nz > 0.7:
        return "floor"
    if nz < -0.7:
        return "ceiling"
    return "wall"


def analyze(path: str) -> dict:
    name = os.path.splitext(os.path.basename(path))[0]
    pkg = u.parse(open(path, "rb").read(), name)

    # ----- (1) material catalog from the import table -----
    # path -> {"class":..., "package":..., "group":..., "name":...}
    catalog: dict = {}
    import_pkg_classes = Counter()  # texture-resource count per source package
    for i, imp in enumerate(pkg.imports):
        if imp.class_name not in MATERIAL_CLASSES:
            continue
        p = pkg._import_path(i)
        parts = p.split(".")
        src_pkg = parts[0] if parts else p
        group = parts[1] if len(parts) >= 3 else ""
        catalog[p] = {
            "class": imp.class_name,
            "package": src_pkg,
            "group": group,
            "name": parts[-1],
        }
        import_pkg_classes[src_pkg] += 1

    # ----- (2) per-surface usage from brush polygons -----
    # texture path -> Counter(role -> poly count)
    tex_role = defaultdict(Counter)
    pkg_role = defaultdict(Counter)         # source package -> role counts
    tex_total = Counter()                   # texture path -> total polys
    pkg_total = Counter()                   # source package -> total polys
    role_total = Counter()                  # floor/wall/ceiling poly totals
    polys_seen = 0
    polys_textured = 0

    for e in pkg.exports:
        if e.class_name != "Brush":
            continue
        props = u.read_properties(pkg, e)
        model_ref = next(
            (p.value.ref for p in props
             if p.name == "Brush" and isinstance(p.value, u.ObjectRef)), 0)
        polys_ref = u.brush_polys_ref(pkg, model_ref)
        if not polys_ref:
            continue
        for fp in u.decode_polys(pkg, polys_ref):
            polys_seen += 1
            role = _surface_role(fp.normal)
            role_total[role] += 1
            tex_path = _qual_to_path(fp.texture.qualified())
            if not tex_path:
                continue
            polys_textured += 1
            src_pkg = tex_path.split(".")[0]
            tex_role[tex_path][role] += 1
            tex_total[tex_path] += 1
            pkg_role[src_pkg][role] += 1
            pkg_total[src_pkg] += 1

    # source packages that actually appear on architectural surfaces (exclude
    # the map's own package and known non-architecture families)
    arch_pkgs = {p: n for p, n in pkg_total.items()
                 if p != name and p not in NON_ARCH_PACKAGES}

    return {
        "map": os.path.basename(path),
        "version": pkg.version,
        "n_material_imports": len(catalog),
        "n_brush_polys": polys_seen,
        "n_polys_textured": polys_textured,
        "role_totals": dict(role_total),
        # source-package poly usage (the theme-cluster signal)
        "package_poly_totals": dict(pkg_total.most_common()),
        "package_role": {p: dict(c) for p, c in pkg_role.items()},
        "arch_package_totals": dict(
            sorted(arch_pkgs.items(), key=lambda kv: -kv[1])),
        # per-texture usage with surface-role split
        "texture_poly_totals": dict(tex_total.most_common()),
        "texture_role": {t: dict(c) for t, c in tex_role.items()},
        # import-table catalog (what the map references, even if rarely used)
        "material_catalog": catalog,
        "import_package_counts": dict(import_pkg_classes.most_common()),
    }


# --------------------------------------------------------------------------- #
# Cross-map clustering
# --------------------------------------------------------------------------- #
def cross_map(results: list) -> dict:
    """Aggregate package usage across all maps + cluster maps by shared
    architectural texture packages (Jaccard over each map's dominant set)."""
    # global package poly usage (architectural only)
    global_pkg = Counter()
    pkg_maps = defaultdict(set)        # package -> set of maps that use it
    for r in results:
        for p, n in r["arch_package_totals"].items():
            global_pkg[p] += n
            pkg_maps[p].add(r["map"])

    # package co-occurrence (appear together within a single map)
    co = Counter()
    for r in results:
        ps = sorted(r["arch_package_totals"].keys())
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                co[(ps[i], ps[j])] += 1

    # per-map "signature": its top architectural packages (>=10% of arch polys)
    signatures = {}
    for r in results:
        tot = sum(r["arch_package_totals"].values()) or 1
        sig = {p for p, n in r["arch_package_totals"].items() if n / tot >= 0.10}
        # always include the single biggest even if <10%
        if r["arch_package_totals"]:
            sig.add(next(iter(r["arch_package_totals"])))
        signatures[r["map"]] = sig

    # greedy clustering by Jaccard similarity of signatures
    maps = list(signatures.keys())
    clusters: list = []
    assigned: set = set()
    THRESH = 0.34
    for m in maps:
        if m in assigned:
            continue
        cluster = [m]
        assigned.add(m)
        for n2 in maps:
            if n2 in assigned:
                continue
            a, b = signatures[m], signatures[n2]
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac >= THRESH:
                cluster.append(n2)
                assigned.add(n2)
        # common packages across the cluster
        common = set.intersection(*(signatures[x] for x in cluster)) \
            if cluster else set()
        clusters.append({
            "maps": cluster,
            "shared_packages": sorted(common),
            "size": len(cluster),
        })
    clusters.sort(key=lambda c: -c["size"])

    # global per-package surface-role split (which packages skew floor vs wall)
    pkg_role_global = defaultdict(Counter)
    for r in results:
        for p, roles in r["package_role"].items():
            if p == os.path.splitext(r["map"])[0] or p in NON_ARCH_PACKAGES:
                continue
            for role, n in roles.items():
                pkg_role_global[p][role] += n

    return {
        "n_maps": len(results),
        "global_arch_package_totals": dict(global_pkg.most_common()),
        "package_map_coverage": {p: len(ms) for p, ms in
                                 sorted(pkg_maps.items(),
                                        key=lambda kv: -len(kv[1]))},
        "top_cooccurrence": [
            {"packages": list(k), "maps_together": v}
            for k, v in co.most_common(40)
        ],
        "package_role_global": {p: dict(c) for p, c in
                                sorted(pkg_role_global.items(),
                                       key=lambda kv: -sum(kv[1].values()))},
        "clusters": clusters,
    }


# --------------------------------------------------------------------------- #
# Text report
# --------------------------------------------------------------------------- #
def _bar(n, total, width=24):
    if not total:
        return ""
    return "#" * int(round(width * n / total))


def print_one(r: dict) -> None:
    print(f"\n== {r['map']} ==")
    print(f"  material imports: {r['n_material_imports']}   "
          f"brush polys: {r['n_brush_polys']} "
          f"({r['n_polys_textured']} textured)")
    rt = r["role_totals"]
    print(f"  surface roles: floor={rt.get('floor',0)} "
          f"wall={rt.get('wall',0)} ceiling={rt.get('ceiling',0)}")
    print("  top texture packages (by poly):")
    for p, n in list(r["arch_package_totals"].items())[:8]:
        roles = r["package_role"].get(p, {})
        rs = " ".join(f"{k[0]}{v}" for k, v in sorted(roles.items()))
        print(f"    {n:5d}  {p:28s} [{rs}]")
    print("  top textures (by poly):")
    for t, n in list(r["texture_poly_totals"].items())[:8]:
        roles = r["texture_role"].get(t, {})
        rs = "/".join(f"{k}:{v}" for k, v in sorted(roles.items()))
        print(f"    {n:5d}  {t:42s} {rs}")


def print_summary(results: list, xm: dict) -> None:
    print("\n" + "=" * 72)
    print("CROSS-MAP TEXTURE PATTERNS (%d maps)" % xm["n_maps"])
    print("=" * 72)

    gp = xm["global_arch_package_totals"]
    cov = xm["package_map_coverage"]
    tot = sum(gp.values()) or 1
    print("\nTop architectural texture packages (poly count / map coverage):")
    for p, n in list(gp.items())[:20]:
        print(f"  {n:6d}  {100*n//tot:3d}%  in {cov.get(p,0):2d} maps  "
              f"{p:28s} {_bar(n, tot)}")

    print("\nPackages on the most maps (ubiquity):")
    for p, c in list(cov.items())[:15]:
        print(f"  {c:2d} maps  {p}")

    print("\nTop package co-occurrences (appear together in a map):")
    for entry in xm["top_cooccurrence"][:15]:
        a, b = entry["packages"]
        print(f"  {entry['maps_together']:2d}x  {a}  +  {b}")

    print("\nPer-package surface-role skew (floor / wall / ceiling polys):")
    for p, roles in list(xm["package_role_global"].items())[:15]:
        t = sum(roles.values()) or 1
        f = roles.get("floor", 0)
        w = roles.get("wall", 0)
        c = roles.get("ceiling", 0)
        print(f"  {p:28s} f={100*f//t:3d}% w={100*w//t:3d}% c={100*c//t:3d}%  "
              f"({t} polys)")

    print("\nTheme clusters (maps grouped by shared architectural packages):")
    for i, cl in enumerate(xm["clusters"], 1):
        shared = ", ".join(cl["shared_packages"]) or "(no common dominant pkg)"
        print(f"\n  Cluster {i} ({cl['size']} maps) -- shared: {shared}")
        for m in sorted(cl["maps"]):
            print(f"     {m}")


def main(argv):
    files = [f for f in argv if not f.startswith("--")]
    as_json = "--json" in argv
    if not files:
        print("usage: texture_survey.py Maps/*.ut2 [--json]", file=sys.stderr)
        return 2
    results = []
    for f in files:
        try:
            results.append(analyze(f))
        except u.ParseError as exc:
            print(f"== {f} ==\n  ERROR: {exc}", file=sys.stderr)
    xm = cross_map(results) if len(results) > 1 else None
    if as_json:
        import json
        out = {"maps": results}
        if xm:
            out["cross_map"] = xm
        print(json.dumps(out, indent=2))
        return 0
    for r in results:
        print_one(r)
    if xm:
        print_summary(results, xm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
