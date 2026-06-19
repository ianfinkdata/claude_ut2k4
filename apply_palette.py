#!/usr/bin/env python3
"""Re-skin a brush T3D by applying a named texture palette per face role.

Reads a palette JSON (see palettes/*.json) and rewrites the `Texture=` token on
every `Begin Polygon` block of a T3D, choosing the texture by the polygon's face
normal: floor (Nz>0.7), ceiling (Nz<-0.7), or wall (otherwise). This is how the
procedural pipeline themes a room module's geometry without touching UnrealEd.

Usage:
    python apply_palette.py IN.t3d palettes/tech-rankin.json -o OUT.t3d

stdlib only. The role rule matches surveys/texture_survey.py so themed output is
consistent with the survey data the palette was derived from.
"""
import argparse
import json
import re
import sys

NORMAL_RE = re.compile(r"Normal\s+([-+0-9.]+),([-+0-9.]+),([-+0-9.]+)")
POLY_RE = re.compile(r"^(\s*Begin Polygon)(.*)$")


def role_for(nz, floor_thresh=0.7):
    if nz > floor_thresh:
        return "floor"
    if nz < -floor_thresh:
        return "ceiling"
    return "wall"


def set_texture(attrs, texture):
    """Replace or insert the Texture= token on a Begin Polygon attribute string,
    preserving other attributes (Link=, Flags=, Item=, ...)."""
    if re.search(r"\bTexture=\S+", attrs):
        return re.sub(r"\bTexture=\S+", f"Texture={texture}", attrs)
    # insert right after the leading space so it reads naturally
    return f" Texture={texture}{attrs}"


def apply_palette(lines, surfaces):
    out = []
    counts = {"wall": 0, "floor": 0, "ceiling": 0}
    i = 0
    while i < len(lines):
        m = POLY_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        # find this polygon's Normal in the following lines (within the block)
        nz = 0.0
        for j in range(i + 1, min(i + 12, len(lines))):
            nm = NORMAL_RE.search(lines[j])
            if nm:
                nz = float(nm.group(3))
                break
            if "End Polygon" in lines[j]:
                break
        role = role_for(nz)
        tex = surfaces.get(role) or surfaces.get("wall")
        out.append(m.group(1) + set_texture(m.group(2), tex))
        counts[role] += 1
        i += 1
    return out, counts


def main():
    ap = argparse.ArgumentParser(description="Apply a texture palette to a brush T3D by face role.")
    ap.add_argument("t3d", help="input T3D file")
    ap.add_argument("palette", help="palette JSON (palettes/*.json)")
    ap.add_argument("-o", "--out", required=True, help="output T3D file")
    args = ap.parse_args()

    pal = json.load(open(args.palette, encoding="utf-8"))
    surfaces = pal.get("surfaces", {})
    if not surfaces:
        sys.exit(f"palette {args.palette} has no 'surfaces' map")

    lines = open(args.t3d, encoding="utf-8").read().splitlines()
    out, counts = apply_palette(lines, surfaces)
    open(args.out, "w", encoding="utf-8").write("\n".join(out) + "\n")

    total = sum(counts.values())
    print(f"Applied palette '{pal.get('name','?')}' to {total} polygons: "
          f"{counts['wall']} wall -> {surfaces.get('wall')}, "
          f"{counts['floor']} floor -> {surfaces.get('floor')}, "
          f"{counts['ceiling']} ceiling -> {surfaces.get('ceiling')}")
    print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
