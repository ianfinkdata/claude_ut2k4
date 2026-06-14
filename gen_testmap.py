#!/usr/bin/env python3
"""gen_testmap.py — procedurally generate a minimal UT2004 DM test-map skeleton as T3D.

Emits a paste-ready ``Begin Map ... End Map`` block: a hollow room (CSG_Subtract
box brush), a small CSG_Add platform in the centre, ceiling lights, four
PlayerStarts, four PathNodes, and four Pickup/InventorySpot pairs (one of each
of the major categories: health, ammo, adrenaline, weapon) per the 1:1
anchoring rule in NAV_PATTERNS.md.

This is the "from-scratch" half of the pipeline described in CLAUDE.md: paste
the output into a new UnrealEd level, then Build Geometry -> Build Lighting ->
Build Paths -> Play, to validate the procedural-generation concept end to end.

The box-brush polygon template (face order, normals, winding, texture axes)
was reverse-engineered from two real, working, byte-identical-verified stock
brushes (DM-Gael Brush9 — a CSG_Subtract cube — and DM-Rankin Brush340 — a
CSG_Add box), confirming the same outward-normal convention applies to both
CSG operations.

Usage:
    python3 gen_testmap.py > import_kit/TestMap-Skeleton.t3d
    python3 gen_testmap.py -o import_kit/TestMap-Skeleton.t3d
"""
import argparse
import decimal
import math

_DEC6 = decimal.Decimal("0.000001")


def fnum(v: float) -> str:
    """%.6f with half-away-from-zero rounding, matching the engine's T3D export."""
    return f"{decimal.Decimal(v).quantize(_DEC6, rounding=decimal.ROUND_HALF_UP):.6f}"


def bnum(v: float) -> str:
    """+013.6f signed/padded form used inside Begin Brush polygon blocks."""
    if v == 0.0:
        v = 0.0
    return f"{decimal.Decimal(v).quantize(_DEC6, rounding=decimal.ROUND_HALF_UP):+013.6f}"


def bvec(x: float, y: float, z: float) -> str:
    return ",".join(bnum(c) for c in (x, y, z))


def fmt_vec(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> str:
    """Location/PrePivot-style vector: omit zero components (matches engine
    T3D output), but always emit at least one component."""
    parts = [f"{k}={fnum(c)}" for k, c in zip("XYZ", (x, y, z)) if c != 0.0]
    if not parts:
        parts = [f"X={fnum(0.0)}"]
    return "(" + ",".join(parts) + ")"


def fmt_rot(pitch: int = 0, yaw: int = 0, roll: int = 0):
    parts = [f"{k}={v}" for k, v in (("Pitch", pitch), ("Yaw", yaw), ("Roll", roll)) if v]
    return "(" + ",".join(parts) + ")" if parts else None


# ---------------------------------------------------------------------------
# Box-brush polygon template
# ---------------------------------------------------------------------------

def box_faces(hx: float, hy: float, hz: float):
    """Six (normal, textureU, textureV, [4 verts]) faces for an axis-aligned
    box of half-extents (hx,hy,hz) centred on the brush's local origin.

    Face order, normals, winding and texture axes were derived from two real
    stock brushes (DM-Gael Brush9 / DM-Rankin Brush340) and are identical for
    CSG_Add and CSG_Subtract brushes -- the polygon always describes the
    OUTWARD-facing surface of the brush's solid volume.
    """
    return [
        # -X
        ((-1, 0, 0), (0, 1, 0), (0, 0, -1),
         [(-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz)]),
        # +Y
        ((0, 1, 0), (1, 0, 0), (0, 0, -1),
         [(-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz)]),
        # +X
        ((1, 0, 0), (0, -1, 0), (0, 0, -1),
         [(hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz), (hx, -hy, -hz)]),
        # -Y
        ((0, -1, 0), (-1, 0, 0), (0, 0, -1),
         [(hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz), (-hx, -hy, -hz)]),
        # +Z
        ((0, 0, 1), (1, 0, 0), (0, 1, 0),
         [(-hx, hy, hz), (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz)]),
        # -Z
        ((0, 0, -1), (1, 0, 0), (0, -1, 0),
         [(-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz)]),
    ]


def brush_actor(name: str, model_name: str, csg_op: str, location, half_extents,
                texture: str = None) -> list:
    hx, hy, hz = half_extents
    lines = [
        f"Begin Actor Class=Brush Name={name}",
        f"    CsgOper={csg_op}",
        "    MainScale=(SheerAxis=SHEER_ZX)",
        "    PostScale=(SheerAxis=SHEER_ZX)",
        '    Tag="Brush"',
        f"    Location={fmt_vec(*location)}",
        f"    Begin Brush Name={model_name}",
        "       Begin PolyList",
    ]
    for normal, tex_u, tex_v, verts in box_faces(hx, hy, hz):
        head = "          Begin Polygon"
        if texture:
            head += f" Texture={texture}"
        lines.append(head)
        lines.append(f"             Origin   {bvec(*verts[0])}")
        lines.append(f"             Normal   {bvec(*normal)}")
        lines.append(f"             TextureU {bvec(*tex_u)}")
        lines.append(f"             TextureV {bvec(*tex_v)}")
        for v in verts:
            lines.append(f"             Vertex   {bvec(*v)}")
        lines.append("          End Polygon")
    lines += [
        "       End PolyList",
        "    End Brush",
        f"    Brush=Model'MyLevel.{model_name}'",
        "End Actor",
    ]
    return lines


# ---------------------------------------------------------------------------
# Non-brush actors
# ---------------------------------------------------------------------------

def light_actor(name: str, location, brightness=64.0, radius=64) -> list:
    return [
        f"Begin Actor Class=Light Name={name}",
        f"    LightBrightness={fnum(brightness)}",
        f"    LightRadius={radius}",
        '    Tag="Light"',
        f"    Location={fmt_vec(*location)}",
        "End Actor",
    ]


def player_start_actor(name: str, location, yaw: int = 0) -> list:
    lines = [
        f"Begin Actor Class=PlayerStart Name={name}",
        '    Tag="PlayerStart"',
        f"    Location={fmt_vec(*location)}",
    ]
    rot = fmt_rot(yaw=yaw)
    if rot:
        lines.append(f"    Rotation={rot}")
    lines.append("End Actor")
    return lines


def path_node_actor(name: str, location) -> list:
    return [
        f"Begin Actor Class=PathNode Name={name}",
        '    Tag="PathNode"',
        f"    Location={fmt_vec(*location)}",
        "End Actor",
    ]


def pickup_actor(cls: str, name: str, location, marker_name: str) -> list:
    return [
        f"Begin Actor Class={cls} Name={name}",
        f'    Tag="{cls}"',
        f"    myMarker=InventorySpot'MyLevel.{marker_name}'",
        f"    Location={fmt_vec(*location)}",
        "End Actor",
    ]


def weapon_charger_actor(name: str, weapon_class: str, location, marker_name: str,
                          static_mesh: str = "2k4ChargerMeshes.ChargerMeshes.WeaponChargerMesh-DS",
                          pre_pivot_z: float = 3.7) -> list:
    """xWeaponBase 'weapon charger' pickup -- the stock-map pattern for placing
    a weapon (StaticMesh-driven). A bare Weapon-class actor (e.g. ShockRifle)
    has a skeletal view-mesh that crashes UnrealEd's editor-viewport renderer
    (USkeletalMeshInstance::Render GPF) when placed directly, so we always use
    the charger wrapper instead."""
    return [
        f"Begin Actor Class=xWeaponBase Name={name}",
        f"    WeaponType=Class'{weapon_class}'",
        f"    myMarker=InventorySpot'MyLevel.{marker_name}'",
        f"    StaticMesh=StaticMesh'{static_mesh}'",
        '    Tag="xWeaponBase"',
        f"    Location={fmt_vec(*location)}",
        f"    PrePivot={fmt_vec(0.0, 0.0, pre_pivot_z)}",
        "End Actor",
    ]


def inventory_spot_actor(name: str, location, item_cls: str, item_name: str,
                          link_prop: str = "markedItem") -> list:
    return [
        f"Begin Actor Class=InventorySpot Name={name}",
        '    Tag="InventorySpot"',
        f"    {link_prop}={item_cls}'MyLevel.{item_name}'",
        f"    Location={fmt_vec(*location)}",
        "End Actor",
    ]


# ---------------------------------------------------------------------------
# Map assembly
# ---------------------------------------------------------------------------

def build_map(room_xy: float = 768.0, room_h: float = 384.0) -> list:
    """A single square room, floor at Z=0, ceiling at Z=room_h, spanning
    [-room_xy, +room_xy] on X and Y."""
    lines = ["Begin Map"]

    # Room shell: hollow it out of the (empty) level with one big Subtract box.
    lines += brush_actor("RoomShell", "ModelRoomShell", "CSG_Subtract",
                          location=(0, 0, room_h / 2),
                          half_extents=(room_xy, room_xy, room_h / 2))

    # A small solid platform in the centre (CSG_Add), for visual interest and
    # as a jump/pathing obstacle.
    plat_h = 64.0
    lines += brush_actor("CenterPlatform", "ModelCenterPlatform", "CSG_Add",
                          location=(0, 0, plat_h / 2),
                          half_extents=(128.0, 128.0, plat_h / 2))

    # Ceiling lights: one centred, four over the room's quadrants.
    light_z = room_h - 34.0
    for i, (x, y) in enumerate([(0, 0), (400, 400), (-400, 400), (400, -400), (-400, -400)]):
        lines += light_actor(f"Light{i}", (x, y, light_z))

    # PlayerStarts at the four corners, facing the centre.
    inset = room_xy - 218.0
    for i, (sx, sy) in enumerate([(1, 1), (-1, 1), (-1, -1), (1, -1)]):
        x, y = sx * inset, sy * inset
        yaw = round(math.degrees(math.atan2(-y, -x)) / 360.0 * 65536.0)
        lines += player_start_actor(f"PlayerStart{i}", (x, y, 16.0), yaw=yaw)

    # PathNodes at the wall midpoints, linking the corners to the centre.
    mid = room_xy - 118.0
    for i, (x, y) in enumerate([(0, mid), (0, -mid), (mid, 0), (-mid, 0)]):
        lines += path_node_actor(f"PathNode{i}", (x, y, 16.0))

    # Pickups + their InventorySpots (1:1 anchoring, spot floor-snapped below
    # the pickup), one per major category, ringed around the centre platform.
    pickups = [
        ("MiniHealthPack", (0, 300)),
        ("ShockAmmoPickup", (0, -300)),
        ("AdrenalinePickup", (-300, 0)),
    ]
    for i, (cls, (x, y)) in enumerate(pickups):
        pickup_name = f"{cls}0"
        spot_name = f"InventorySpot{i}"
        lines += pickup_actor(cls, pickup_name, (x, y, 16.0), spot_name)
        lines += inventory_spot_actor(spot_name, (x, y, 0.0), cls, pickup_name)

    # Weapon: xWeaponBase charger (StaticMesh-driven) rather than a bare
    # Weapon actor -- see weapon_charger_actor() docstring.
    weapon_name = "xWeaponBase0"
    weapon_spot = f"InventorySpot{len(pickups)}"
    lines += weapon_charger_actor(weapon_name, "XWeapons.ShockRifle", (300, 0, 16.0), weapon_spot)
    lines += inventory_spot_actor(weapon_spot, (300, 0, 0.0), "xWeaponBase", weapon_name,
                                   link_prop="myPickupBase")

    lines.append("End Map")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", help="output .t3d path (default: stdout)")
    ap.add_argument("--room-xy", type=float, default=768.0,
                    help="room half-extent on X/Y (default 768 -> 1536x1536 room)")
    ap.add_argument("--room-h", type=float, default=384.0,
                    help="room height (default 384)")
    args = ap.parse_args()

    text = "\n".join(build_map(args.room_xy, args.room_h)) + "\n"
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
