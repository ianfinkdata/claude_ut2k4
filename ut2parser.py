#!/usr/bin/env python3
"""Parser for UT2004 (Unreal Engine 2) package files (.ut2 and friends).

Reads the binary Unreal package format: header -> name table -> import table
-> export table -> serialized object data. Recovers everything that parses
reliably (header, the three tables, the actor/object list) so a map can be
enumerated. Geometry blobs (BSP, brush polys, lightmaps) are intentionally
left as opaque object data -- see CLAUDE.md for the read-binary/write-T3D plan.

Format references: BeyondUnreal Wiki "Package File Format", EliotVU, and the
shrimpza/unreal-package-lib Java implementation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = 0x9E2A83C1
RF_HAS_STACK = 0x02000000  # export's serial data is prefixed with an FStateFrame

# Tagged-property type ids (Unreal Engine 2)
PROP_BYTE, PROP_INT, PROP_BOOL, PROP_FLOAT, PROP_OBJECT = 1, 2, 3, 4, 5
PROP_NAME, PROP_STRING, PROP_CLASS, PROP_ARRAY, PROP_STRUCT = 6, 7, 8, 9, 10
PROP_VECTOR, PROP_ROTATOR, PROP_STR, PROP_MAP, PROP_FIXEDARRAY = 11, 12, 13, 14, 15

PROP_TYPE_NAMES = {
    1: "Byte", 2: "Int", 3: "Bool", 4: "Float", 5: "Object", 6: "Name",
    7: "String", 8: "Class", 9: "Array", 10: "Struct", 11: "Vector",
    12: "Rotator", 13: "Str", 14: "Map", 15: "FixedArray",
}

# size descriptor (bits 4-6 of the info byte) -> fixed byte count; 5/6/7 mean
# the size follows as a u8/u16/u32 respectively.
_SIZE_TABLE = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}


class ParseError(Exception):
    """Raised when the byte stream does not match the expected package format."""


# --------------------------------------------------------------------------- #
# Core decoders
# --------------------------------------------------------------------------- #
class Reader:
    """Cursor over a bytes buffer with the Unreal primitive decoders."""

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def guid(self) -> str:
        raw = self.data[self.pos : self.pos + 16]
        self.pos += 16
        return raw.hex()

    def compact_index(self) -> int:
        """Decode a signed compact index: 1-5 bytes.

        Byte 0: bit 7 (0x80) = sign, bit 6 (0x40) = continuation, bits 0-5 = low
        value bits. Subsequent bytes: bit 7 = continuation, bits 0-6 = value bits.
        """
        b = self.data[self.pos]
        self.pos += 1
        negative = bool(b & 0x80)
        value = b & 0x3F
        if b & 0x40:
            shift = 6
            for _ in range(4):  # at most 4 more bytes
                b = self.data[self.pos]
                self.pos += 1
                value |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
        return -value if negative else value

    def fstring(self) -> str:
        """Length-prefixed ANSI string (length is a compact index, incl. the
        trailing NUL). UT2004 uses compact-index-prefixed ANSI for name entries.
        A negative length would signal UTF-16; stock maps don't use it here, but
        we handle it defensively."""
        length = self.compact_index()
        if length == 0:
            return ""
        if length < 0:  # UTF-16, length is in characters
            n = -length
            raw = self.data[self.pos : self.pos + n * 2]
            self.pos += n * 2
            return raw.decode("utf-16-le").rstrip("\x00")
        raw = self.data[self.pos : self.pos + length]
        self.pos += length
        return raw.decode("latin-1").rstrip("\x00")


# --------------------------------------------------------------------------- #
# Table records
# --------------------------------------------------------------------------- #
@dataclass
class NameEntry:
    name: str
    flags: int


@dataclass
class ImportEntry:
    class_package_idx: int
    class_name_idx: int
    outer_ref: int  # object reference (int32): >0 export, <0 import, 0 none
    object_name_idx: int
    # resolved for convenience
    class_package: str = ""
    class_name: str = ""
    object_name: str = ""


@dataclass
class ExportEntry:
    class_ref: int  # object reference
    super_ref: int  # object reference
    outer_ref: int  # int32 object reference (group/package)
    object_name_idx: int
    flags: int
    serial_size: int
    serial_offset: int
    # resolved for convenience
    object_name: str = ""
    class_name: str = ""


# --------------------------------------------------------------------------- #
# Package
# --------------------------------------------------------------------------- #
@dataclass
class Package:
    version: int = 0
    licensee_version: int = 0
    package_flags: int = 0
    guid: str = ""
    generations: list = field(default_factory=list)
    names: list = field(default_factory=list)        # list[NameEntry]
    imports: list = field(default_factory=list)      # list[ImportEntry]
    exports: list = field(default_factory=list)      # list[ExportEntry]
    raw: bytes = b""                                 # full file bytes (for serial data)
    package_name: str = ""                           # the map's own package name (filename stem)

    # ----- reference resolution ----- #
    def name(self, idx: int) -> str:
        if 0 <= idx < len(self.names):
            return self.names[idx].name
        return f"<bad-name:{idx}>"

    def object_name(self, ref: int) -> str:
        """Resolve a signed object reference to a readable name."""
        if ref == 0:
            return "None"
        if ref > 0:
            i = ref - 1
            if i < len(self.exports):
                return self.exports[i].object_name
            return f"<bad-export:{ref}>"
        i = -ref - 1
        if i < len(self.imports):
            return self.imports[i].object_name
        return f"<bad-import:{ref}>"

    def _import_path(self, i: int) -> str:
        """Dotted path of an import, walking its outer chain (e.g.
        'HumanoidArchitecture.Bases.bas02HAb')."""
        imp = self.imports[i]
        outer = imp.outer_ref
        if outer < 0 and -outer - 1 < len(self.imports):
            return self._import_path(-outer - 1) + "." + imp.object_name
        if outer > 0 and outer - 1 < len(self.exports):
            return self.package_name + "." + self.exports[outer - 1].object_name \
                + "." + imp.object_name
        return imp.object_name

    def _export_path(self, i: int) -> str:
        """Dotted path of an export, walking its outer chain and prefixing the
        package name (e.g. 'DM-Rankin.Pipes.SC-BronzPipe', or flat
        'DM-Rankin.LevelInfo0' for a top-level object)."""
        e = self.exports[i]
        outer = e.outer_ref
        if outer > 0 and outer - 1 < len(self.exports):
            return self._export_path(outer - 1) + "." + e.object_name
        if outer < 0 and -outer - 1 < len(self.imports):
            return self._import_path(-outer - 1) + "." + e.object_name
        return (self.package_name or "Package") + "." + e.object_name

    def qualified_ref(self, ref: int) -> str:
        """T3D-style reference: Class'Package.Name'  (or None)."""
        if ref == 0:
            return "None"
        if ref > 0:
            i = ref - 1
            if i < len(self.exports):
                return f"{self.exports[i].class_name}'{self._export_path(i)}'"
            return "None"
        i = -ref - 1
        if i < len(self.imports):
            imp = self.imports[i]
            return f"{imp.class_name}'{self._import_path(i)}'"
        return "None"


class ObjectRef:
    """An object/class property value. Stringifies to the plain object name (keeps
    summaries/JSON readable) but can render the qualified T3D form on demand."""

    __slots__ = ("pkg", "ref")

    def __init__(self, pkg: Package, ref: int):
        self.pkg = pkg
        self.ref = ref

    @property
    def name(self) -> str:
        return self.pkg.object_name(self.ref)

    def qualified(self) -> str:
        return self.pkg.qualified_ref(self.ref)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"ObjectRef({self.name!r})"


def parse(data: bytes, package_name: str = "") -> Package:
    r = Reader(data)
    magic = r.u32()
    if magic != MAGIC:
        raise ParseError(
            f"bad magic 0x{magic:08X} (expected 0x{MAGIC:08X}); not an Unreal package"
        )

    pkg = Package()
    pkg.raw = data
    pkg.package_name = package_name
    pkg.version = r.u16()
    pkg.licensee_version = r.u16()
    pkg.package_flags = r.u32()

    name_count = r.u32()
    name_offset = r.u32()
    export_count = r.u32()
    export_offset = r.u32()
    import_count = r.u32()
    import_offset = r.u32()
    pkg.guid = r.guid()

    gen_count = r.u32()
    for _ in range(gen_count):
        exp = r.u32()
        nam = r.u32()
        pkg.generations.append((exp, nam))

    # --- name table --- #
    r.pos = name_offset
    for _ in range(name_count):
        nm = r.fstring()
        flags = r.u32()
        pkg.names.append(NameEntry(nm, flags))

    # --- import table --- #
    r.pos = import_offset
    for _ in range(import_count):
        e = ImportEntry(
            class_package_idx=r.compact_index(),
            class_name_idx=r.compact_index(),
            outer_ref=r.i32(),
            object_name_idx=r.compact_index(),
        )
        e.class_package = pkg.name(e.class_package_idx)
        e.class_name = pkg.name(e.class_name_idx)
        e.object_name = pkg.name(e.object_name_idx)
        pkg.imports.append(e)

    # --- export table --- #
    r.pos = export_offset
    for _ in range(export_count):
        class_ref = r.compact_index()
        super_ref = r.compact_index()
        outer_ref = r.i32()
        object_name_idx = r.compact_index()
        flags = r.u32()
        serial_size = r.compact_index()
        serial_offset = r.compact_index() if serial_size > 0 else 0
        e = ExportEntry(
            class_ref=class_ref,
            super_ref=super_ref,
            outer_ref=outer_ref,
            object_name_idx=object_name_idx,
            flags=flags,
            serial_size=serial_size,
            serial_offset=serial_offset,
        )
        e.object_name = pkg.name(object_name_idx)
        pkg.exports.append(e)

    # second pass: resolve export class names (need the full export list first)
    for e in pkg.exports:
        e.class_name = pkg.object_name(e.class_ref) if e.class_ref != 0 else "Class"

    return pkg


# --------------------------------------------------------------------------- #
# Tagged-property decoding (per-export serial data)
# --------------------------------------------------------------------------- #
@dataclass
class Property:
    name: str
    type_id: int
    type_name: str
    value: object              # interpreted value, or raw bytes when undecoded
    struct_name: str = ""      # for StructProperty
    array_index: int = 0


def _read_array_index(r: Reader) -> int:
    """Array element index, present when the info byte's 0x80 bit is set on a
    non-bool property. Variable 1/2/4-byte big-endian-ish encoding."""
    b = r.u8()
    if b < 0x80:
        return b
    if (b & 0xC0) == 0x80:
        return ((b & 0x7F) << 8) | r.u8()
    return ((b & 0x3F) << 24) | (r.u8() << 16) | (r.u8() << 8) | r.u8()


def _skip_stateframe(r: Reader) -> None:
    """Skip the FStateFrame that prefixes serial data when RF_HasStack is set:
    Node + StateNode (object refs), ProbeMask (qword), LatentAction (dword),
    and Offset (compact index) when Node is non-null."""
    node = r.compact_index()
    r.compact_index()      # StateNode
    r.pos += 8             # ProbeMask (QWORD)
    r.pos += 4             # LatentAction (DWORD)
    if node != 0:
        r.compact_index()  # Offset into the bytecode


def _read_struct_value(r: Reader, struct_name: str, size: int) -> object:
    start = r.pos
    if struct_name == "Vector" and size >= 12:
        return (r.f32(), r.f32(), r.f32())
    if struct_name == "Rotator" and size >= 12:
        return {"pitch": r.i32(), "yaw": r.i32(), "roll": r.i32()}
    if struct_name == "Color" and size >= 4:
        b, g, rr, a = r.u8(), r.u8(), r.u8(), r.u8()
        return {"r": rr, "g": g, "b": b, "a": a}
    if struct_name == "Scale" and size >= 12:
        out = {"scale": (r.f32(), r.f32(), r.f32())}
        if size >= 16:
            out["sheerRate"] = r.f32()
        if size >= 17:
            out["sheerAxis"] = r.u8()
        return out
    # Quat, Box, PointRegion, and anything else: raw bytes (caller realigns)
    return r.data[start : start + size]


def _read_value(r: Reader, pkg: Package, type_id: int, struct_name: str,
                size: int, start: int) -> object:
    if type_id == PROP_BYTE:
        return r.u8()
    if type_id == PROP_INT:
        return r.i32()
    if type_id == PROP_FLOAT:
        return r.f32()
    if type_id in (PROP_OBJECT, PROP_CLASS):
        return ObjectRef(pkg, r.compact_index())
    if type_id == PROP_NAME:
        return pkg.name(r.compact_index())
    if type_id in (PROP_STR, PROP_STRING):
        return r.fstring()
    if type_id == PROP_STRUCT:
        return _read_struct_value(r, struct_name, size)
    # Array, Map, FixedArray, Bool (handled earlier), unknown -> raw bytes
    return r.data[start : start + size]


def read_properties(pkg: Package, export: ExportEntry) -> list:
    """Decode the tagged-property list of one export. Returns list[Property]."""
    if export.serial_size <= 0:
        return []
    r = Reader(pkg.raw, export.serial_offset)
    if export.flags & RF_HAS_STACK:
        _skip_stateframe(r)
    end = export.serial_offset + export.serial_size
    props = []
    while r.pos < end:
        name = pkg.name(r.compact_index())
        if name == "None":
            break
        info = r.u8()
        type_id = info & 0x0F

        struct_name = ""
        if type_id == PROP_STRUCT:
            struct_name = pkg.name(r.compact_index())

        size_field = (info >> 4) & 0x07
        if size_field < 5:
            size = _SIZE_TABLE[size_field]
        elif size_field == 5:
            size = r.u8()
        elif size_field == 6:
            size = r.u16()
        else:
            size = r.u32()

        is_bool = type_id == PROP_BOOL
        array_index = 0
        if (info & 0x80) and not is_bool:
            array_index = _read_array_index(r)

        if is_bool:
            value = bool(info & 0x80)
        else:
            value_start = r.pos
            value = _read_value(r, pkg, type_id, struct_name, size, value_start)
            r.pos = value_start + size  # guarantee alignment regardless of decode

        props.append(
            Property(name, type_id, PROP_TYPE_NAMES.get(type_id, str(type_id)),
                     value, struct_name, array_index)
        )
    return props


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _summary(path: str, pkg: Package, top: int = 25) -> str:
    from collections import Counter

    lines = []
    lines.append(f"== {path} ==")
    lines.append(
        f"version={pkg.version} licensee={pkg.licensee_version} "
        f"flags=0x{pkg.package_flags:08X} guid={pkg.guid}"
    )
    lines.append(
        f"names={len(pkg.names)} imports={len(pkg.imports)} exports={len(pkg.exports)}"
    )

    class_counts = Counter(e.class_name for e in pkg.exports)
    lines.append("")
    lines.append(f"top {top} object classes (by export count):")
    for cls, n in class_counts.most_common(top):
        lines.append(f"  {n:6d}  {cls}")

    # imported packages this map depends on
    dep_pkgs = sorted(
        {imp.object_name for imp in pkg.imports if imp.class_name == "Package"}
    )
    if dep_pkgs:
        lines.append("")
        lines.append("imported packages (dependencies):")
        lines.append("  " + ", ".join(dep_pkgs))

    return "\n".join(lines)


def _fmt_vec(v) -> str:
    if isinstance(v, tuple) and len(v) == 3:
        return f"({v[0]:.1f}, {v[1]:.1f}, {v[2]:.1f})"
    return str(v)


def _actors_report(path: str, pkg: Package) -> str:
    """List every placed actor (exports that carry a Location) with its class,
    location, and rotation -- the structured per-actor data from Step 2."""
    lines = [f"== {path} -- actors =="]
    count = 0
    for e in pkg.exports:
        props = {p.name: p for p in read_properties(pkg, e) if p.array_index == 0}
        if "Location" not in props:
            continue
        count += 1
        loc = _fmt_vec(props["Location"].value)
        rot = ""
        if "Rotation" in props and isinstance(props["Rotation"].value, dict):
            r = props["Rotation"].value
            rot = f"  rot(p={r['pitch']},y={r['yaw']},r={r['roll']})"
        lines.append(f"  {e.class_name:22s} {e.object_name:24s} {loc}{rot}")
    lines.insert(1, f"{count} placed actors")
    return "\n".join(lines)


def _jsonify(v):
    """Make a decoded property value JSON-serializable."""
    if isinstance(v, ObjectRef):
        return v.name
    if isinstance(v, bytes):
        return {"_raw_hex": v.hex()}
    if isinstance(v, tuple):
        return [_jsonify(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonify(x) for k, x in v.items()}
    return v


def actor_model(pkg: Package, path: str, actors_only: bool = True) -> dict:
    """Build a machine-readable model of a map: every (actor) export with its
    class and decoded properties. Repeated array elements collapse into a list."""
    import os

    objs = []
    for i, e in enumerate(pkg.exports):
        props = read_properties(pkg, e)
        if actors_only and not any(p.name == "Location" for p in props):
            continue
        pd: dict = {}
        for p in props:
            jv = _jsonify(p.value)
            if p.array_index or p.name in pd:  # array element
                cur = pd.get(p.name)
                if not isinstance(cur, list):
                    cur = [] if cur is None else [cur]
                    pd[p.name] = cur
                while len(cur) <= p.array_index:
                    cur.append(None)
                cur[p.array_index] = jv
            else:
                pd[p.name] = jv
        objs.append({"index": i + 1, "class": e.class_name,
                     "name": e.object_name, "properties": pd})
    return {
        "file": os.path.basename(path),
        "version": pkg.version,
        "actor_count": len(objs),
        "actors": objs,
    }


def _diff_report(path_a: str, pkg_a: Package, path_b: str, pkg_b: Package) -> str:
    """Compare two maps by per-class actor counts."""
    import os
    from collections import Counter

    a = actor_model(pkg_a, path_a)
    b = actor_model(pkg_b, path_b)
    ca = Counter(x["class"] for x in a["actors"])
    cb = Counter(x["class"] for x in b["actors"])

    na, nb = os.path.basename(path_a), os.path.basename(path_b)
    lines = [f"== diff: {na}  vs  {nb} =="]
    lines.append(f"{'class':24s} {na:>16s} {nb:>16s}   delta")
    for cls in sorted(ca.keys() | cb.keys()):
        x, y = ca.get(cls, 0), cb.get(cls, 0)
        mark = "" if x == y else "  <--"
        lines.append(f"{cls:24s} {x:16d} {y:16d}   {y - x:+d}{mark}")
    lines.append("-" * 60)
    lines.append(f"{'TOTAL actors':24s} {len(a['actors']):16d} {len(b['actors']):16d}   "
                 f"{len(b['actors']) - len(a['actors']):+d}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# T3D generation (write side -- Step 4)
# --------------------------------------------------------------------------- #
# Properties the engine recomputes on build; never emit them.
_T3D_SKIP_PROPS = {"Region", "ColLocation"}

# Additionally dropped in "clean" mode: level-binding refs that point at objects
# of the source map (LevelInfo, PhysicsVolume, the nav chain). Meaningless when
# pasting into a different/empty level, where they'd just raise "object not found".
_T3D_CLEAN_EXTRA = {"Level", "PhysicsVolume", "Base", "nextNavigationPoint",
                    "PendingTouch", "Owner"}


def _fmt_float(v: float) -> str:
    return f"{v:.6f}"


def _fmt_vec_t3d(comps, keys) -> str:
    return "(" + ",".join(f"{k}={_fmt_float(c)}" for k, c in zip(keys, comps)) + ")"


# Vector-valued properties whose per-component default is 1.0 (scales) rather
# than 0.0. The engine omits components equal to their default in T3D export.
_SCALE_VECTORS = {"DrawScale3D"}


def _fmt_vec_default(comps, keys, default: float) -> str:
    parts = [f"{k}={_fmt_float(c)}" for k, c in zip(keys, comps) if c != default]
    if not parts:  # all-default (shouldn't serialize) -- emit first component
        parts = [f"{keys[0]}={_fmt_float(comps[0])}"]
    return "(" + ",".join(parts) + ")"


def _fmt_struct(struct_name: str, value, prop_name: str = "") -> str:
    if struct_name == "Vector" and isinstance(value, (list, tuple)):
        default = 1.0 if prop_name in _SCALE_VECTORS else 0.0
        return _fmt_vec_default(value, "XYZ", default)
    if struct_name == "Rotator" and isinstance(value, dict):
        parts = [f"{k}={value[k.lower()]}" for k in ("Pitch", "Yaw", "Roll")
                 if value.get(k.lower())]
        return "(" + ",".join(parts) + ")" if parts else "(Yaw=0)"
    if struct_name == "Color" and isinstance(value, dict):
        return f"(R={value['r']},G={value['g']},B={value['b']},A={value['a']})"
    if struct_name == "Scale" and isinstance(value, dict):
        s = _fmt_vec_t3d(value["scale"], "XYZ")
        out = f"(Scale={s}"
        if value.get("sheerRate"):
            out += f",SheerRate={_fmt_float(value['sheerRate'])}"
        return out + ")"
    return ""  # undecodable struct -> skip


def _fmt_prop_value(p) -> str:
    """Render one decoded Property as a T3D value, or '' to skip it."""
    t = p.type_id
    v = p.value
    if t == PROP_BOOL:
        return "True" if v else "False"
    if t in (PROP_INT, PROP_BYTE):
        return str(v)
    if t == PROP_FLOAT:
        return _fmt_float(v)
    if t in (PROP_OBJECT, PROP_CLASS):
        return v.qualified() if isinstance(v, ObjectRef) else "None"
    if t == PROP_NAME:
        return f'"{v}"'
    if t in (PROP_STR, PROP_STRING):
        return f'"{v}"'
    if t == PROP_STRUCT:
        return _fmt_struct(p.struct_name, v, p.name)
    return ""  # Array / Map / raw -> skip for now


def to_t3d(pkg: Package, classes=None, clean: bool = False) -> str:
    """Generate Map T3D for the placed actors (exports with a Location). Emits
    the properties we can faithfully represent; arrays and engine-recomputed
    fields are skipped. With clean=True, also drops level-binding refs so the
    actors paste cleanly into an empty/other level. Suitable for UnrealEd paste."""
    skip = _T3D_SKIP_PROPS | _T3D_CLEAN_EXTRA if clean else _T3D_SKIP_PROPS
    lines = ["Begin Map"]
    for e in pkg.exports:
        if classes and e.class_name not in classes:
            continue
        props = read_properties(pkg, e)
        if not any(p.name == "Location" for p in props):
            continue
        lines.append(f"Begin Actor Class={e.class_name} Name={e.object_name}")
        for p in props:
            if p.name in skip:
                continue
            s = _fmt_prop_value(p)
            if not s:
                continue
            key = f"{p.name}({p.array_index})" if p.array_index else p.name
            lines.append(f"    {key}={s}")
        lines.append("End Actor")
    lines.append("End Map")
    return "\n".join(lines)


def main(argv: list) -> int:
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="Parse and summarize UT2004 .ut2 packages")
    ap.add_argument("files", nargs="+", help=".ut2 (or other Unreal package) files")
    ap.add_argument("--top", type=int, default=25, help="how many top classes to show")
    ap.add_argument("--actors", action="store_true",
                    help="list placed actors with location/rotation instead of the summary")
    ap.add_argument("--json", action="store_true",
                    help="emit the actor model as JSON")
    ap.add_argument("--all-objects", action="store_true",
                    help="with --json, include every export (not just placed actors)")
    ap.add_argument("--diff", action="store_true",
                    help="compare exactly two maps by per-class actor counts")
    ap.add_argument("--t3d", action="store_true",
                    help="generate actor T3D (write side)")
    ap.add_argument("--t3d-class", metavar="CLASS", action="append",
                    help="restrict --t3d to these actor class(es); repeatable")
    ap.add_argument("--t3d-clean", action="store_true",
                    help="with --t3d, drop level-binding refs for clean paste into a new level")
    args = ap.parse_args(argv)

    def _load(p):
        return parse(open(p, "rb").read(), os.path.splitext(os.path.basename(p))[0])

    if args.diff:
        if len(args.files) != 2:
            ap.error("--diff requires exactly two files")
        pkgs = [_load(p) for p in args.files]
        print(_diff_report(args.files[0], pkgs[0], args.files[1], pkgs[1]))
        return 0

    for path in args.files:
        try:
            pkg = _load(path)
        except ParseError as exc:
            print(f"== {path} ==\n  ERROR: {exc}\n")
            continue
        if args.t3d:
            print(to_t3d(pkg, classes=set(args.t3d_class) if args.t3d_class else None,
                         clean=args.t3d_clean))
        elif args.json:
            model = actor_model(pkg, path, actors_only=not args.all_objects)
            print(json.dumps(model, indent=2))
        elif args.actors:
            print(_actors_report(path, pkg))
            print()
        else:
            print(_summary(path, pkg, args.top))
            print()
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
