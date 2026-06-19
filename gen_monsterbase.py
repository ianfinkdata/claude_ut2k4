#!/usr/bin/env python3
"""gen_monsterbase.py — generate the multi-room "Deathmatch in a monster base" map as T3D.

Layout: a central HUB arena (PlayerStarts + basic weapons, the DM space) with N
escalating gated BRANCHES. Each branch reuses the proven single-room gate pattern
(validated in claude_test_monster_spike.ut2):

    HUB --(open doorway)--> ANTECHAMBER (same-species guardians) --(gated door)--> VAULT (reward)

Players DM in the hub, arm up, fight a branch's guardians; clearing them trips a
Counter that opens the static-mesh Mover door to that branch's reward vault. Only
ONE branch holds the Redeemer (the toughest gate).

Geometry is fully subtractive (the committed map's workflow): subtract room boxes
and doorway connectors from solid world; the uncarved solid between boxes is the
walls. Doors are static-mesh Movers modelled on the user's Mover0 (DT_StaticMesh +
tag-triggered movement). Emits paste-ready T3D; run apply_palette.py afterward to
skin surfaces by face role.

Brush/light/pickup/pathnode emitters are reused from gen_testmap.py (proven).

Usage:
    python3 gen_monsterbase.py -o import_kit/MonsterBase-Full.t3d
"""
import argparse

import gen_testmap as g

# Door mesh: the user's Mover0 template references a MAP-LOCAL mesh
# (claude_test_monster_spike.movers.Door). Map-local meshes do NOT resolve in a
# fresh level, so for a standalone full map this defaults to the same on-theme
# shared door the user skinned toward; swap with --door-mesh if building inside
# the committed package. See MonsterBase-Full-README.md.
DEFAULT_DOOR_MESH = "HumanoidHardware.Miscellaneous.MDoor01HA"

FLOOR_Z = 0.0
CEIL_Z = 384.0
ROOM_HZ = CEIL_Z / 2.0          # half height for subtract boxes
DOOR_HZ = 128.0                 # doorway connector half-height (256 tall opening)
DOORWAY_HALF = 96.0             # doorway half-width (192 opening, matches committed map)


class Namer:
    def __init__(self):
        self.spot = 0

    def next_spot(self):
        n = f"InventorySpot{self.spot}"
        self.spot += 1
        return n


def monster_actor(cls, name, location, yaw, event="MonsterKill"):
    lines = [
        f"Begin Actor Class={cls} Name={name}",
        f'    Event="{event}"',
        f'    Tag="{cls}"',
        f"    Location={g.fmt_vec(*location)}",
    ]
    rot = g.fmt_rot(yaw=yaw)
    if rot:
        lines.append(f"    Rotation={rot}")
    lines.append("End Actor")
    return lines


def counter_actor(name, num, tag, event, location, complete_msg, count_msg):
    return [
        f"Begin Actor Class=Counter Name={name}",
        f"    NumToCount={num}",
        "    bShowMessage=True",
        f'    CountMessage="{count_msg}"',
        f'    CompleteMessage="{complete_msg}"',
        f'    Event="{event}"',
        f'    Tag="{tag}"',
        f"    Location={g.fmt_vec(*location)}",
        "End Actor",
    ]


def door_actor(name, tag, location, yaw, door_mesh, scale_x=0.5, scale_z=0.85,
               open_dz=290.0):
    """Static-mesh Mover door modelled on the user's Mover0 template: a single
    DT_StaticMesh Mover, tag-triggered (TriggerOpenTimed), latching open once.
    Collision comes from the mesh; it slides up `open_dz` to open."""
    lines = [
        f"Begin Actor Class=Mover Name={name}",
        '    InitialState="TriggerOpenTimed"',
        "    bTriggerOnceOnly=True",
        "    MoverEncroachType=ME_IgnoreWhenEncroach",
        "    MoverGlideType=MV_GlideByTime",
        "    MoveTime=2.000000",
        "    StayOpenTime=10000.000000",
        "    KeyNum=0",
        "    NumKeys=2",
        "    KeyPos(0)=(X=0.000000)",
        f"    KeyPos(1)=(Z={g.fnum(open_dz)})",
        "    DrawType=DT_StaticMesh",
        f"    StaticMesh=StaticMesh'{door_mesh}'",
        "    bBlockActors=True",
        "    bBlockPlayers=True",
        f'    Tag="{tag}"',
        f"    Location={g.fmt_vec(*location)}",
    ]
    rot = g.fmt_rot(yaw=yaw)
    if rot:
        lines.append(f"    Rotation={rot}")
    lines.append(f"    DrawScale3D={g.fmt_vec(scale_x, 1.0, scale_z)}")
    lines.append("End Actor")
    return lines


def place_item(cls, name, x, y, namer, z=16.0):
    """A simple pickup (health/ammo/armor/adrenaline) + its 1:1 InventorySpot."""
    spot = namer.next_spot()
    lines = g.pickup_actor(cls, name, (x, y, z), spot)
    lines += g.inventory_spot_actor(spot, (x, y, 0.0), cls, name, link_prop="markedItem")
    return lines


def place_weapon(name, weapon_class, x, y, namer, z=16.0):
    """A weapon charger (xWeaponBase) + its 1:1 InventorySpot."""
    spot = namer.next_spot()
    lines = g.weapon_charger_actor(name, weapon_class, (x, y, z), spot)
    lines += g.inventory_spot_actor(spot, (x, y, 0.0), "xWeaponBase", name,
                                    link_prop="myPickupBase")
    return lines


# Branch geometry constants (flat, single floor) -----------------------------
HUB_HALF = 768.0          # hub half-extent (1536 sq)
WALL = 192.0              # solid wall thickness between boxes
HALF_DEPTH = 320.0        # antechamber / vault half-depth (640 deep each)
ROOM_HALF_W = 512.0       # branch room half-width (1024 wide)


def build_branch(branch, namer):
    """Build one gated branch along an axis direction.

    branch = dict(name, dir(one of N/S/E/W), monster, count, reward_weapon,
                  loadout=[(cls,...)], door_mesh, msgs...)
    Returns T3D line list. All boxes are subtract; door sits in the
    antechamber->vault connector.
    """
    d = branch["dir"]
    nm = branch["name"]
    tag = f"{nm}Gate"
    lines = []

    # Axis setup: 'a' is the branch's long axis (distance from hub), perpendicular is 'p'.
    # antechamber inner edge starts at hub_edge + wall.
    hub_edge = HUB_HALF + WALL                       # = 960
    ante_c = hub_edge + HALF_DEPTH                    # antechamber center along axis
    ante_far = hub_edge + 2 * HALF_DEPTH              # antechamber far edge (= ante boundary)
    vault_c = ante_far + WALL + HALF_DEPTH            # vault center
    door_a = ante_far + WALL / 2.0                    # door sits mid-wall between ante and vault
    hub_door_a = HUB_HALF + WALL / 2.0                # open hub<->antechamber doorway

    sign = {"N": 1, "S": -1, "E": 1, "W": -1}[d]
    axis_is_y = d in ("N", "S")

    def AP(a, p):
        """Map (axis, perp) to world (x, y) for this branch direction."""
        a = sign * a
        return (p, a) if axis_is_y else (a, p)

    def box(name_suf, a_center, half_a, half_p, hz=ROOM_HZ, op="CSG_Subtract"):
        x, y = AP(a_center, 0.0)
        if axis_is_y:
            half = (half_p, half_a, hz)
        else:
            half = (half_a, half_p, hz)
        return g.brush_actor(f"{nm}{name_suf}", f"Model{nm}{name_suf}", op,
                             location=(x, y, hz), half_extents=half)

    # Rooms (subtract): antechamber + vault.
    lines += box("Ante", ante_c, HALF_DEPTH, ROOM_HALF_W)
    lines += box("Vault", vault_c, HALF_DEPTH, ROOM_HALF_W)
    # Doorway connectors (subtract): hub<->ante (open) and ante<->vault (gated).
    lines += box("HubDoor", hub_door_a, WALL / 2.0, DOORWAY_HALF, hz=DOOR_HZ)
    lines += box("GateDoor", door_a, WALL / 2.0, DOORWAY_HALF, hz=DOOR_HZ)

    # Door (Mover) in the gated connector. Yaw orients the mesh width across the
    # opening: doorway opening is along the perpendicular axis.
    dx, dy = AP(door_a, 0.0)
    door_yaw = 16384 if axis_is_y else 0   # mesh long axis -> world perp axis
    lines += door_actor(f"{nm}Door", tag, (dx, dy, FLOOR_Z), door_yaw,
                        branch["door_mesh"])

    # Counter: clearing the guardians (Event="MonsterKill" + this gate's kill tag)
    # opens the door. Each branch's monsters fire a branch-specific kill event.
    kill_event = f"{nm}Kill"
    cx, cy = AP(ante_c, 0.0)
    lines += counter_actor(f"{nm}Counter", branch["count"], kill_event, tag,
                          (cx, cy, FLOOR_Z),
                          complete_msg=branch["complete_msg"],
                          count_msg="Guardian down... %i remain.")

    # Guardians: same species, in the antechamber, spread across the perp axis.
    mz = 80.0 if branch["monster"] == "WarLord" else 24.0
    n = branch["count"]
    for i in range(n):
        # spread along perp axis within the room width
        p = (i - (n - 1) / 2.0) * 200.0
        gx, gy = AP(ante_c, p)
        face_yaw = {"N": 49152, "S": 16384, "E": 32768, "W": 0}[d]  # face back toward hub
        lines += monster_actor(branch["monster"], f"{nm}Guardian{i}", (gx, gy, mz),
                              face_yaw, event=kill_event)

    # Reward weapon: deep in the vault.
    rx, ry = AP(vault_c + HALF_DEPTH - 160.0, 0.0)
    lines += place_weapon(f"{nm}Reward", branch["reward_weapon"], rx, ry, namer)

    # Branch combat loadout (fight the guardians): ammo + health near the
    # hub-side of the antechamber, plus any branch extras.
    ax, ay = AP(ante_c - HALF_DEPTH + 160.0, -260.0)
    bx, by = AP(ante_c - HALF_DEPTH + 160.0, 260.0)
    lines += place_item(branch["ammo"], f"{nm}Ammo", ax, ay, namer)
    lines += place_item("MiniHealthPack", f"{nm}Health", bx, by, namer)
    for j, extra in enumerate(branch.get("extras", [])):
        ex, ey = AP(vault_c - HALF_DEPTH + 140.0, 0.0)
        lines += place_item(extra, f"{nm}Extra{j}", ex, ey, namer)

    # Lights: antechamber + vault centres, mounted high.
    lz = CEIL_Z - 40.0
    for suf, ac in (("AnteL", ante_c), ("VaultL", vault_c)):
        lx, ly = AP(ac, 0.0)
        lines += g.light_actor(f"{nm}{suf}", (lx, ly, lz), brightness=110.0, radius=24)

    # PathNodes: hub-doorway, antechamber centre, gate-doorway, vault centre
    # (keeps every walk hop well under the 1200uu ceiling).
    for suf, ac in (("PNHub", hub_door_a), ("PNAnte", ante_c),
                    ("PNGate", door_a), ("PNVault", vault_c)):
        px, py = AP(ac, 0.0)
        lines += g.path_node_actor(f"{nm}{suf}", (px, py, 16.0))

    return lines


def build_map(door_mesh):
    namer = Namer()
    lines = ["Begin Map"]

    # Hub arena: one big subtract box.
    lines += g.brush_actor("Hub", "ModelHub", "CSG_Subtract",
                           location=(0, 0, ROOM_HZ),
                           half_extents=(HUB_HALF, HUB_HALF, ROOM_HZ))

    # Hub lights (4 quadrants + centre), mounted high.
    lz = CEIL_Z - 40.0
    for i, (x, y) in enumerate([(0, 0), (380, 380), (-380, 380), (380, -380), (-380, -380)]):
        lines += g.light_actor(f"HubLight{i}", (x, y, lz), brightness=120.0, radius=28)

    # Hub PlayerStarts (8, ringed, facing centre).
    import math
    for i in range(8):
        ang = i / 8.0 * 2 * math.pi
        x, y = 560.0 * math.cos(ang), 560.0 * math.sin(ang)
        yaw = round(math.degrees(math.atan2(-y, -x)) / 360.0 * 65536.0) % 65536
        lines += g.player_start_actor(f"HubStart{i}", (x, y, 16.0), yaw=yaw)

    # Hub central PathNode + ring nodes (connectivity, walk gaps < 1200).
    lines += g.path_node_actor("HubPNC", (0, 0, 16.0))
    for i, (x, y) in enumerate([(360, 0), (-360, 0), (0, 360), (0, -360)]):
        lines += g.path_node_actor(f"HubPN{i}", (x, y, 16.0))

    # Hub basic loadout: two starter weapons + ammo + health + adrenaline.
    lines += place_weapon("HubShock", "XWeapons.ShockRifle", 300, 300, namer)
    lines += place_weapon("HubLink", "XWeapons.LinkGun", -300, -300, namer)
    lines += place_item("ShockAmmoPickup", "HubAmmo", 300, -300, namer)
    lines += place_item("MiniHealthPack", "HubHealth", -300, 300, namer)
    lines += place_item("AdrenalinePickup", "HubAdren", 0, 420, namer)

    # Branches: escalating; exactly ONE holds the Redeemer (West).
    branches = [
        dict(name="N", dir="N", monster="Gasbag", count=2,
             reward_weapon="XWeapons.FlakCannon", ammo="FlakAmmoPickup",
             complete_msg="The north vault opens.", door_mesh=door_mesh),
        dict(name="E", dir="E", monster="Skaarj", count=3,
             reward_weapon="XWeapons.RocketLauncher", ammo="RocketAmmoPickup",
             extras=["ShieldPack"],
             complete_msg="The east vault opens.", door_mesh=door_mesh),
        dict(name="W", dir="W", monster="WarLord", count=5,
             reward_weapon="XWeapons.Redeemer", ammo="RocketAmmoPickup",
             extras=["ShieldPack"],
             complete_msg="The Redeemer is yours... if you survive.", door_mesh=door_mesh),
    ]
    for b in branches:
        lines += build_branch(b, namer)

    lines.append("End Map")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", help="output .t3d (default stdout)")
    ap.add_argument("--door-mesh", default=DEFAULT_DOOR_MESH,
                    help=f"static mesh for Mover doors (default {DEFAULT_DOOR_MESH}; "
                         "use the committed map's local 'movers.Door' if building inside it)")
    args = ap.parse_args()
    text = "\n".join(build_map(args.door_mesh)) + "\n"
    if args.output:
        open(args.output, "w").write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
