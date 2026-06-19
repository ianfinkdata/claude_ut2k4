#!/usr/bin/env python3
"""Room / brush geometry survey across the UT2004 DM map inventory.

The SPATIAL BACKBONE for modular generation (see PLAN_MONSTERBASE.md, Agent #5).
Where navanalysis.py mines the bot-path graph (footprint via nav-node bbox,
verticality via node Z), this script mines the actual CSG BRUSH geometry:

 - Room footprints: world-space bounding boxes of CSG_Subtract brushes (the
   hollow spaces players move through) -- width x depth x height distributions.
 - Ceiling heights: the Z extent of those subtract volumes.
 - Corridor widths: the narrow horizontal dimension of elongated subtract
   brushes (aspect-ratio > 2 -> treat the short side as a passage width).
 - Doorway / opening dimensions: derived from the SHARED FACES between adjacent
   subtract brushes -- where two hollow volumes touch on a common plane, the
   overlap rectangle of that contact is the opening between them (see
   doorway notes in ROOM_PATTERNS.md for what is and isn't extractable).
 - A recommended module grid unit (does the data cluster on 256uu?) and a
   doorway "port" spec the module system standardizes on.

Brush transform note: across all 39 stock maps, ZERO subtract brushes carry a
non-identity Rotation, so subtract volumes are axis-aligned. World-space vertex
= (localVertex - PrePivot) * MainScale.Scale * PostScale.Scale + Location.
That makes an axis-aligned bounding box exact (no rotated-hull approximation).

Run:  python surveys/geometry_survey.py Maps/DM-*.ut2          # full report
      python surveys/geometry_survey.py Maps/DM-Rankin.ut2     # one map
      python surveys/geometry_survey.py Maps/DM-*.ut2 --json    # machine-readable
"""

from __future__ import annotations

import glob
import math
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ut2parser as u  # noqa: E402

# A subtract brush smaller than this in any dimension is structural detail
# (a recess, trim cut, window slot) rather than a room/corridor a player walks.
MIN_ROOM_DIM = 64.0
# A subtract brush larger than this in ALL horizontal dims is a world-envelope
# fill (sky/sea cube, e.g. the 131072uu engine-max cube), not a player room.
# Counted separately; excluded from room/corridor/ceiling distributions.
MAX_ROOM_DIM = 8192.0
# Aspect ratio (long horiz / short horiz) above which a subtract volume reads as
# a corridor/passage rather than a room; its short side is the corridor width.
CORRIDOR_ASPECT = 2.0
# How close two brush faces must be (uu) to count as a shared/contact plane.
FACE_TOL = 2.0
# Common grid candidates we test the footprint/height data against.
GRID_CANDIDATES = [128, 192, 256, 320, 512]
# Player metrics (UT2004): pawn collision radius ~25uu, height ~44uu half =>
# ~88uu standing; jump clearance wants ~ headroom. Used to sanity-floor ports.
PLAYER_HEIGHT = 88.0


def _scale_vec(struct_val):
    """Pull the Scale (X,Y,Z) tuple out of a MainScale/PostScale struct value,
    defaulting to (1,1,1) when absent or undecoded."""
    if isinstance(struct_val, dict):
        sc = struct_val.get("Scale")
        if isinstance(sc, (list, tuple)) and len(sc) == 3:
            return (float(sc[0]), float(sc[1]), float(sc[2]))
    return (1.0, 1.0, 1.0)


def _brush_world_bbox(pkg, export, props):
    """Axis-aligned world-space bbox of one Brush actor's polygon vertices.
    Returns ((minx,miny,minz),(maxx,maxy,maxz)) or None. Applies PrePivot,
    MainScale, PostScale and Location (rotation is always identity for stock
    subtract brushes -- asserted by the survey before trusting AABBs)."""
    bp = props.get("Brush")
    if bp is None or not isinstance(bp.value, u.ObjectRef):
        return None
    polys_ref = u.brush_polys_ref(pkg, bp.value.ref)
    if not polys_ref:
        return None
    polys = u.decode_polys(pkg, polys_ref)
    if not polys:
        return None

    loc = props["Location"].value if "Location" in props else (0.0, 0.0, 0.0)
    pre = props["PrePivot"].value if "PrePivot" in props \
        and isinstance(props["PrePivot"].value, tuple) else (0.0, 0.0, 0.0)
    msc = _scale_vec(props["MainScale"].value) if "MainScale" in props else (1, 1, 1)
    psc = _scale_vec(props["PostScale"].value) if "PostScale" in props else (1, 1, 1)
    sx, sy, sz = msc[0] * psc[0], msc[1] * psc[1], msc[2] * psc[2]

    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    for fp in polys:
        for v in fp.vertices:
            wx = (v[0] - pre[0]) * sx + loc[0]
            wy = (v[1] - pre[1]) * sy + loc[1]
            wz = (v[2] - pre[2]) * sz + loc[2]
            lo[0] = min(lo[0], wx); hi[0] = max(hi[0], wx)
            lo[1] = min(lo[1], wy); hi[1] = max(hi[1], wy)
            lo[2] = min(lo[2], wz); hi[2] = max(hi[2], wz)
    if not all(map(math.isfinite, lo + hi)):
        return None
    return (tuple(lo), tuple(hi))


def _is_rotated(props):
    r = props.get("Rotation")
    if r is None or not isinstance(r.value, dict):
        return False
    return bool(r.value.get("pitch") or r.value.get("yaw") or r.value.get("roll"))


def _overlap_1d(a0, a1, b0, b1):
    """Length of the overlap of intervals [a0,a1] and [b0,b1] (0 if disjoint)."""
    return max(0.0, min(a1, b1) - max(a0, b0))


def _shared_openings(boxes):
    """Derive opening rectangles from CONTACT between subtract volumes.

    For each pair of axis-aligned subtract boxes that touch (or overlap) on a
    common plane along one axis, the connection between them is the rectangle
    where they overlap in the OTHER two axes. That rectangle's width (smaller
    horizontal side) and height (Z side) approximate the doorway/opening between
    the two hollow spaces. Returns list of (width, height) tuples.

    This is an APPROXIMATION: it reports the contact aperture between adjacent
    hollow volumes, not the modeled door frame (which is built from separate
    additive trim brushes). See ROOM_PATTERNS.md for the honest assessment.
    """
    openings = []
    n = len(boxes)
    for i in range(n):
        (ax0, ay0, az0), (ax1, ay1, az1) = boxes[i]
        for j in range(i + 1, n):
            (bx0, by0, bz0), (bx1, by1, bz1) = boxes[j]
            # quick reject: must overlap or touch on all three axes
            ox = _overlap_1d(ax0, ax1, bx0, bx1)
            oy = _overlap_1d(ay0, ay1, by0, by1)
            oz = _overlap_1d(az0, az1, bz0, bz1)
            # gap (negative overlap) tolerance along each axis
            gx = max(0.0, max(ax0, bx0) - min(ax1, bx1))
            gy = max(0.0, max(ay0, by0) - min(ay1, by1))
            gz = max(0.0, max(az0, bz0) - min(az1, bz1))
            # contact on the X plane: faces meet in X, overlap in Y and Z
            if gx <= FACE_TOL and oy > MIN_ROOM_DIM and oz > MIN_ROOM_DIM \
                    and ox <= FACE_TOL + 1:
                openings.append((oy, oz))
            elif gy <= FACE_TOL and ox > MIN_ROOM_DIM and oz > MIN_ROOM_DIM \
                    and oy <= FACE_TOL + 1:
                openings.append((ox, oz))
            # (skip Z-plane contact: stacked floors are not lateral doorways)
    return openings


def _round_grid(v, grid):
    return round(v / grid)


def analyze(path: str) -> dict:
    pkg = u.parse(open(path, "rb").read(),
                  os.path.splitext(os.path.basename(path))[0])

    sub_boxes = []          # world AABBs of CSG_Subtract brushes (for openings)
    add_count = 0
    rotated_subtracts = 0
    world_fills = 0         # oversized world-envelope subtracts (sky/sea cube)
    room_dims = []          # (w, d, h) sorted-horizontal for "room-like" volumes
    corridor_widths = []    # short horizontal side of elongated volumes
    ceiling_heights = []    # Z extent of room-like volumes

    for e in pkg.exports:
        if e.class_name != "Brush":
            continue
        props = {p.name: p for p in u.read_properties(pkg, e)}
        csg = str(props["CsgOper"].value) if "CsgOper" in props else ""
        if csg.endswith("Add"):
            add_count += 1
            continue
        if not csg.endswith("Subtract"):
            continue
        if _is_rotated(props):
            rotated_subtracts += 1
        bbox = _brush_world_bbox(pkg, e, props)
        if bbox is None:
            continue
        (x0, y0, z0), (x1, y1, z1) = bbox
        w, d, h = x1 - x0, y1 - y0, z1 - z0
        if min(w, d, h) < MIN_ROOM_DIM:
            continue  # detail cut, not a navigable volume
        hs = sorted([w, d])           # [short, long] horizontal
        if hs[0] >= MAX_ROOM_DIM:
            world_fills += 1          # giant world-envelope cube, not a room
            continue
        sub_boxes.append(bbox)
        room_dims.append((hs[0], hs[1], h))
        ceiling_heights.append(h)
        if hs[1] / hs[0] >= CORRIDOR_ASPECT:
            corridor_widths.append(hs[0])

    openings = _shared_openings(sub_boxes)
    op_w = sorted(o[0] for o in openings)
    op_h = sorted(o[1] for o in openings)

    # footprint area per room (short*long horizontal), in sq uu
    footprints = sorted(hs * hl for hs, hl, _ in room_dims)

    # grid alignment test: what fraction of room edges (the 6 bbox planes) sit
    # near a multiple of each grid candidate? Best grid maximizes alignment.
    grid_fit = {}
    edges = []
    for (x0, y0, z0), (x1, y1, z1) in sub_boxes:
        edges.extend([x0, x1, y0, y1, z0, z1])
    for g in GRID_CANDIDATES:
        if not edges:
            grid_fit[g] = 0.0
            continue
        hits = sum(1 for v in edges
                   if abs(v - round(v / g) * g) <= max(1.0, g * 0.02))
        grid_fit[g] = hits / len(edges)

    def _st(vals):
        if not vals:
            return {"n": 0, "min": 0, "median": 0, "mean": 0, "max": 0}
        return {"n": len(vals), "min": round(min(vals), 1),
                "median": round(statistics.median(vals), 1),
                "mean": round(statistics.mean(vals), 1),
                "max": round(max(vals), 1)}

    return {
        "map": os.path.basename(path),
        "subtract_brushes": len(sub_boxes),
        "add_brushes": add_count,
        "rotated_subtracts": rotated_subtracts,
        "world_fills": world_fills,
        "room_dim_short": _st([r[0] for r in room_dims]),
        "room_dim_long": _st([r[1] for r in room_dims]),
        "ceiling_height": _st(ceiling_heights),
        "footprint_area": _st(footprints),
        "corridor_width": _st(corridor_widths),
        "opening_width": _st(op_w),
        "opening_height": _st(op_h),
        "opening_count": len(openings),
        "grid_fit": {str(g): round(v, 3) for g, v in grid_fit.items()},
        # raw lists kept for cross-map aggregation (trimmed out of print view)
        "_room_short": [r[0] for r in room_dims],
        "_room_long": [r[1] for r in room_dims],
        "_ceilings": ceiling_heights,
        "_corridors": corridor_widths,
        "_op_w": op_w,
        "_op_h": op_h,
        "_edges_grid_hits": {str(g): (
            sum(1 for v in edges if abs(v - round(v / g) * g) <= max(1.0, g * 0.02)),
            len(edges)) for g in GRID_CANDIDATES},
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _hist(vals, edges, label):
    """ASCII histogram of vals into the given bin edges."""
    if not vals:
        return [f"  {label}: (no data)"]
    counts = [0] * (len(edges) + 1)
    for v in vals:
        placed = False
        for i, e in enumerate(edges):
            if v < e:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    tot = len(vals)
    out = [f"  {label} (n={tot}):"]
    lbls = [f"<{edges[0]:.0f}"] + \
           [f"{edges[i-1]:.0f}-{edges[i]:.0f}" for i in range(1, len(edges))] + \
           [f">={edges[-1]:.0f}"]
    for lbl, c in zip(lbls, counts):
        bar = "#" * int(round(40 * c / tot)) if tot else ""
        out.append(f"    {lbl:>12s} {c:5d}  {bar}")
    return out


def print_one(a):
    print(f"\n== {a['map']} ==")
    print(f"  subtract brushes (room-like): {a['subtract_brushes']}"
          f"   add brushes: {a['add_brushes']}"
          f"   world-fills: {a['world_fills']}"
          f"   rotated subtracts: {a['rotated_subtracts']}")
    for key, lbl in [("room_dim_short", "room short side"),
                     ("room_dim_long", "room long side"),
                     ("ceiling_height", "ceiling height"),
                     ("corridor_width", "corridor width"),
                     ("opening_width", "opening width"),
                     ("opening_height", "opening height")]:
        s = a[key]
        print(f"  {lbl:16s} n={s['n']:4d}  min={s['min']:7.0f}"
              f"  median={s['median']:7.0f}  max={s['max']:8.0f}")
    print(f"  openings detected: {a['opening_count']}")
    print(f"  grid alignment fraction: " +
          ", ".join(f"{g}uu={v:.2f}" for g, v in a["grid_fit"].items()))


def print_summary(results):
    print("\n" + "=" * 72)
    print("CROSS-MAP GEOMETRY PATTERNS (%d maps)" % len(results))
    print("=" * 72)

    def gather(key):
        out = []
        for r in results:
            out.extend(r[key])
        return out

    all_short = gather("_room_short")
    all_long = gather("_room_long")
    all_ceil = gather("_ceilings")
    all_corr = gather("_corridors")
    all_opw = gather("_op_w")
    all_oph = gather("_op_h")

    def st(vals, lbl):
        if not vals:
            print(f"  {lbl}: (no data)")
            return
        v = sorted(vals)
        q1 = v[len(v) // 4]
        q3 = v[(3 * len(v)) // 4]
        print(f"  {lbl:18s} n={len(v):6d}  min={v[0]:7.0f}  q1={q1:7.0f}"
              f"  median={statistics.median(v):7.0f}  q3={q3:7.0f}"
              f"  max={v[-1]:8.0f}")

    print(f"\nTotal room-like subtract volumes: {len(all_short)}")
    st(all_short, "room short side")
    st(all_long, "room long side")
    st(all_ceil, "ceiling height")
    st(all_corr, "corridor width")
    st(all_opw, "opening width")
    st(all_oph, "opening height")

    print("\n--- Distributions ---")
    for line in _hist(all_ceil, [128, 192, 256, 320, 384, 448, 512, 640, 768, 1024],
                      "ceiling height (uu)"):
        print(line)
    for line in _hist(all_corr, [96, 128, 160, 192, 256, 320, 384, 512],
                      "corridor width (uu)"):
        print(line)
    for line in _hist(all_opw, [64, 96, 128, 160, 192, 256, 320, 512],
                      "opening width (uu)"):
        print(line)
    for line in _hist(all_oph, [96, 128, 160, 192, 256, 320, 448, 640],
                      "opening height (uu)"):
        print(line)

    print("\n--- Grid alignment (fraction of brush-face planes near a grid line) ---")
    grid_tot = defaultdict(lambda: [0, 0])
    for r in results:
        for g, (hits, tot) in r["_edges_grid_hits"].items():
            grid_tot[g][0] += hits
            grid_tot[g][1] += tot
    for g in sorted(grid_tot, key=lambda x: int(x)):
        hits, tot = grid_tot[g]
        frac = hits / tot if tot else 0
        bar = "#" * int(round(40 * frac))
        print(f"  {g:>4s}uu  {frac:.3f}  {bar}")

    rotated = sum(r["rotated_subtracts"] for r in results)
    print(f"\nRotated subtract brushes across all maps: {rotated} "
          f"(AABB footprint is {'exact' if rotated == 0 else 'approximate'})")

    # Most common ceiling heights snapped to 32uu, to spot the modal room height
    snap = Counter(int(round(c / 32.0) * 32) for c in all_ceil)
    print("\nModal ceiling heights (snapped to 32uu):")
    for val, n in snap.most_common(10):
        print(f"  {val:5d} uu  x{n}")


def main(argv):
    files = [f for f in argv if not f.startswith("--")]
    as_json = "--json" in argv
    # default: all stock DM maps (exclude the user playtest skeleton)
    if not files:
        files = [f for f in sorted(glob.glob("Maps/*.ut2"))
                 if "claude_test" not in f]
    results = [analyze(f) for f in files]

    if as_json:
        import json
        # build a cross-map aggregate alongside per-map records
        def gather(key):
            out = []
            for r in results:
                out.extend(r[key])
            return out

        def st(vals):
            if not vals:
                return {"n": 0}
            v = sorted(vals)
            return {"n": len(v), "min": round(v[0], 1),
                    "q1": round(v[len(v) // 4], 1),
                    "median": round(statistics.median(v), 1),
                    "q3": round(v[(3 * len(v)) // 4], 1),
                    "max": round(v[-1], 1)}

        grid_tot = defaultdict(lambda: [0, 0])
        for r in results:
            for g, (hits, tot) in r["_edges_grid_hits"].items():
                grid_tot[g][0] += hits
                grid_tot[g][1] += tot

        agg = {
            "maps": len(results),
            "room_short": st(gather("_room_short")),
            "room_long": st(gather("_room_long")),
            "ceiling_height": st(gather("_ceilings")),
            "corridor_width": st(gather("_corridors")),
            "opening_width": st(gather("_op_w")),
            "opening_height": st(gather("_op_h")),
            "rotated_subtracts": sum(r["rotated_subtracts"] for r in results),
            "grid_alignment": {g: round(h / t, 3) if t else 0
                               for g, (h, t) in grid_tot.items()},
        }
        # strip the bulky raw lists from per-map records for the JSON file
        clean = []
        for r in results:
            clean.append({k: v for k, v in r.items()
                          if not k.startswith("_")})
        print(json.dumps({"cross_map": agg, "maps": clean}, indent=2))
        return 0

    for r in results:
        print_one(r)
    if len(results) > 1:
        print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
