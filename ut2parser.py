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

import json
import os
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


class EnumValue:
    """A byte property resolved to its enum name via the class schema. Prints the
    bare enum identifier (which is also the T3D form, e.g. LE_NonIncidence)."""

    __slots__ = ("name", "index")

    def __init__(self, name: str, index: int):
        self.name = name
        self.index = index

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"EnumValue({self.name!r})"


# --------------------------------------------------------------------------- #
# Class schema (enum value lists + array inner-types), built by schema_extractor
# from the engine's UnrealScript. Optional: parsing still works without it,
# arrays/enum-bytes just stay as raw bytes / numbers.
# --------------------------------------------------------------------------- #
_SCHEMA = None
# Array inner types serialized inline as struct bytes -> leave raw (not object refs).
_STRUCT_INNERS = {"Vector", "Rotator", "Color", "Plane", "Quat", "Box", "Coords",
                  "Matrix", "Range", "RangeVector", "IntBox", "FloatBox"}
_PRIM_INNERS = {"int", "float", "byte", "bool", "name", "string", "str"}


def schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.json")
        try:
            with open(path) as fh:
                _SCHEMA = json.load(fh)
        except (OSError, ValueError):
            _SCHEMA = {"enum_props": {}, "array_props": {}}
    return _SCHEMA


def _decode_array(pkg: Package, raw: bytes, inner: str):
    """Decode a dynamic-array property value (compact count + N elements) using
    the inner element type from the schema. Returns a list, or None to keep raw."""
    if inner in _STRUCT_INNERS:
        return None
    try:
        r = Reader(raw, 0)
        count = r.compact_index()
        if count < 0 or count > len(raw):
            return None
        out = []
        for _ in range(count):
            if inner == "int":
                out.append(r.i32())
            elif inner == "float":
                out.append(r.f32())
            elif inner in ("byte", "bool"):
                out.append(r.u8())
            elif inner == "name":
                out.append(pkg.name(r.compact_index()))
            elif inner in ("string", "str"):
                out.append(r.fstring())
            else:  # a class name -> element is an object reference
                out.append(ObjectRef(pkg, r.compact_index()))
        if inner in _PRIM_INNERS or all(
                not isinstance(el, ObjectRef)
                or -len(pkg.imports) <= el.ref <= len(pkg.exports)
                for el in out):
            if r.pos == len(raw):
                return out
        # didn't consume exactly as refs/prims: try array-of-tagged-structs
        # (e.g. Emitter ColorScale/SizeScale: each element is a nested
        # tagged-property stream terminated by 'None')
        r = Reader(raw, 0)
        count = r.compact_index()
        out = []
        for _ in range(count):
            sub = _parse_tagged(pkg, r, len(raw))
            out.append(TaggedStruct(inner,
                                    {(p.name if not p.array_index
                                      else f"{p.name}({p.array_index})"): p.value
                                     for p in sub}))
        if r.pos == len(raw):
            return out
        return None
    except (IndexError, struct.error, UnicodeDecodeError):
        return None


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


class TaggedStruct(dict):
    """A non-native struct decoded from its nested tagged-property stream
    (e.g. Scale, PointRegion). Behaves as a dict of subprop name -> value."""

    def __init__(self, struct_name: str, values: dict):
        super().__init__(values)
        self.struct_name = struct_name


def _read_struct_value(r: Reader, pkg: Package, struct_name: str, size: int) -> object:
    start = r.pos
    if struct_name == "Vector" and size >= 12:
        return (r.f32(), r.f32(), r.f32())
    if struct_name == "Rotator" and size >= 12:
        return {"pitch": r.i32(), "yaw": r.i32(), "roll": r.i32()}
    if struct_name == "Color" and size >= 4:
        b, g, rr, a = r.u8(), r.u8(), r.u8(), r.u8()
        return {"r": rr, "g": g, "b": b, "a": a}
    # Non-native structs (Scale, PointRegion, ...) serialize as a NESTED
    # tagged-property stream terminated by 'None'. Parse it; fall back to raw
    # bytes if it doesn't consume the value exactly.
    try:
        sub = _parse_tagged(pkg, r, start + size)
        if r.pos == start + size:
            return TaggedStruct(struct_name,
                                {(p.name if not p.array_index
                                  else f"{p.name}({p.array_index})"): p.value
                                 for p in sub})
    except (IndexError, struct.error, UnicodeDecodeError):
        pass
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
        return _read_struct_value(r, pkg, struct_name, size)
    # Array, Map, FixedArray, Bool (handled earlier), unknown -> raw bytes
    return r.data[start : start + size]


@dataclass
class FPoly:
    """One brush polygon, decoded from a Polys object's native serialization."""
    base: tuple
    normal: tuple
    texture_u: tuple
    texture_v: tuple
    vertices: list
    texture: ObjectRef
    item: str
    flags: int
    link: int


def model_polys_ref(pkg: Package, model_ref: int):
    """Given an editor-brush Model object reference, return the index of its
    Polys export (or None). Deterministically parses the UModel header:
    None-terminator, UPrimitive bounds, 5 empty BSP arrays, NumSharedSides,
    NumZones, then the Polys object reference."""
    if model_ref <= 0 or model_ref > len(pkg.exports):
        return None
    m = pkg.exports[model_ref - 1]
    if m.class_name != "Model":
        return None
    try:
        r = Reader(pkg.raw, m.serial_offset)
        if r.compact_index() != 0:       # empty tagged-property list
            return None
        r.pos += 24 + 1 + 16             # FBox(24) + IsValid(1) + FSphere(16)
        for i in range(5):               # Vectors, Points, Nodes, Surfs, Verts
            cnt = r.compact_index()
            if cnt:
                if i < 2:                # Vectors/Points: FVector = 12 bytes each
                    r.pos += cnt * 12
                else:                    # built BSP (Nodes/Surfs/Verts) -> not an editor brush
                    return None
        r.i32()                          # NumSharedSides
        if r.i32() != 0:                 # NumZones (editor brushes: 0)
            return None
        ref = r.compact_index()          # Polys object reference
        if 0 < ref <= len(pkg.exports) and pkg.exports[ref - 1].class_name == "Polys":
            return ref
    except (IndexError, struct.error):
        pass
    return None


def brush_polys_ref(pkg: Package, model_ref: int):
    """Resolve a Model to its Polys export, including volume Models that carry
    built BSP (where the deterministic header parse bails). Fallback: scan the
    Model's serial bytes for compact indices resolving to Polys exports not
    claimed by any deterministic parse; tie-break by serial-offset proximity."""
    ref = model_polys_ref(pkg, model_ref)
    if ref:
        return ref
    if model_ref <= 0 or model_ref > len(pkg.exports):
        return None
    m = pkg.exports[model_ref - 1]
    if m.class_name != "Model":
        return None
    claimed = getattr(pkg, "_claimed_polys", None)
    if claimed is None:
        claimed = set()
        for e in pkg.exports:
            if e.class_name == "Model":
                r = model_polys_ref(pkg, pkg.exports.index(e) + 1)
                if r:
                    claimed.add(r)
        pkg._claimed_polys = claimed
    cands = set()
    for off in range(m.serial_size):
        try:
            v = Reader(pkg.raw, m.serial_offset + off).compact_index()
        except (IndexError, struct.error):
            continue
        if (0 < v <= len(pkg.exports) and v not in claimed
                and pkg.exports[v - 1].class_name == "Polys"):
            cands.add(v)
    if not cands:
        return None
    return min(cands, key=lambda v: abs(pkg.exports[v - 1].serial_offset
                                        - m.serial_offset))


def decode_polys(pkg: Package, polys_ref: int) -> list:
    """Decode a Polys object into a list of FPoly. Serial layout: None-terminator,
    int32 Num, int32 Max, then Num FPolys (NumVerts byte, Base/Normal/TextureU/
    TextureV vectors, NumVerts vertex vectors, flags, Actor/Texture/Item refs,
    iLink, iBrushPoly, trailing int32)."""
    e = pkg.exports[polys_ref - 1]
    r = Reader(pkg.raw, e.serial_offset)
    end = e.serial_offset + e.serial_size
    if r.compact_index() != 0:
        return []
    num = r.i32()
    r.i32()  # Max
    vec = lambda: (r.f32(), r.f32(), r.f32())
    polys = []
    try:
        for _ in range(num):
            nv = r.u8()
            base, normal, tu, tv = vec(), vec(), vec(), vec()
            verts = [vec() for _ in range(nv)]
            flags = r.i32()
            r.compact_index()                       # Actor (brush back-ref)
            texture = ObjectRef(pkg, r.compact_index())
            item = pkg.name(r.compact_index())
            link = r.compact_index()
            r.compact_index()                       # iBrushPoly
            r.i32()                                 # PanU/PanV/ShadowMapScale slot
            if r.pos > end:
                break
            polys.append(FPoly(base, normal, tu, tv, verts, texture, item, flags, link))
    except (IndexError, struct.error):
        pass
    return polys


def read_properties(pkg: Package, export: ExportEntry) -> list:
    """Decode the tagged-property list of one export. Returns list[Property]."""
    if export.serial_size <= 0:
        return []
    r = Reader(pkg.raw, export.serial_offset)
    if export.flags & RF_HAS_STACK:
        _skip_stateframe(r)
    return _parse_tagged(pkg, r, export.serial_offset + export.serial_size)


def _parse_tagged(pkg: Package, r: Reader, end: int) -> list:
    """Parse a tagged-property stream (used for export serial data AND for
    nested non-native structs). Returns list[Property]."""
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

            # schema-driven refinement: name enum bytes, decode known arrays
            sch = schema()
            if type_id == PROP_BYTE and name in sch["enum_props"]:
                vals = sch["enum_props"][name]
                if 0 <= value < len(vals):
                    value = EnumValue(vals[value], value)
            elif type_id == PROP_ARRAY and name in sch["array_props"]:
                decoded = _decode_array(pkg, value, sch["array_props"][name])
                if decoded is not None:
                    value = decoded

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
    if isinstance(v, EnumValue):
        return v.name
    if isinstance(v, list):
        return [_jsonify(x) for x in v]
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
# Properties the engine recomputes on build. Now decodable (nested tagged
# structs), so they ARE emitted -- the engine's own exporter emits them too.
_T3D_SKIP_PROPS = set()

# Additionally dropped in "clean" mode: level-binding refs that point at objects
# of the source map (LevelInfo, PhysicsVolume, the nav chain). Meaningless when
# pasting into a different/empty level, where they'd just raise "object not found".
_T3D_CLEAN_EXTRA = {"Level", "PhysicsVolume", "Base", "nextNavigationPoint",
                    "PendingTouch", "Owner"}


_DEC6 = None


def _fmt_float(v: float) -> str:
    """%f with C-style rounding (half away from zero); Python's format() rounds
    half-to-even, which diverges from the engine on exact .xxxxx5 float values."""
    global _DEC6
    import decimal
    import math
    if not math.isfinite(v) or abs(v) >= 1e15:
        return f"{v:.6f}"
    if _DEC6 is None:
        _DEC6 = decimal.Decimal("0.000001")
    d = decimal.Decimal(v).quantize(_DEC6, rounding=decimal.ROUND_HALF_UP)
    return f"{d:.6f}"


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


def _fmt_color(value: dict) -> str:
    """Engine prints colors in storage order B,G,R,A and omits zero channels."""
    parts = [f"{k}={value[k.lower()]}" for k in ("B", "G", "R", "A")
             if value.get(k.lower())]
    return "(" + ",".join(parts) + ")" if parts else ""


def _fmt_subvalue(sub: str, v) -> str:
    """Format one nested-struct member value, '' to omit (default-zero)."""
    if isinstance(v, tuple) and len(v) == 3:           # vector member
        dflt = 1.0 if sub == "Scale" else 0.0
        if all(c == dflt for c in v):
            return ""
        return _fmt_vec_default(v, "XYZ", dflt)
    if isinstance(v, TaggedStruct):                    # nested struct member
        return _fmt_struct(v.struct_name, v, sub)
    if isinstance(v, dict):                            # Rotator or Color member
        if "pitch" in v:
            parts = [f"{k}={v[k.lower()]}" for k in ("Pitch", "Yaw", "Roll")
                     if v.get(k.lower())]
            return "(" + ",".join(parts) + ")" if parts else ""
        if "r" in v:
            return _fmt_color(v)
        return ""
    if isinstance(v, EnumValue):
        return v.name if v.index else ""
    if isinstance(v, ObjectRef):
        return v.qualified()
    if isinstance(v, bool):
        return "True" if v else ""
    if isinstance(v, float):
        return _fmt_float(v) if v != 0.0 else ""
    if isinstance(v, int):
        return str(v) if v else ""                     # omit default-zero
    if isinstance(v, str):
        return v
    return ""


def _fmt_struct(struct_name: str, value, prop_name: str = "") -> str:
    if struct_name == "Vector" and isinstance(value, (list, tuple)):
        default = 1.0 if prop_name in _SCALE_VECTORS else 0.0
        return _fmt_vec_default(value, "XYZ", default)
    if isinstance(value, TaggedStruct):
        # nested tagged struct (Scale, PointRegion, emitter ranges, ...):
        # emit serialized members, omitting default-zero values like the engine
        parts = []
        for sub, v in value.items():
            s = _fmt_subvalue(sub, v)
            if s:
                parts.append(f"{sub}={s}")
        return "(" + ",".join(parts) + ")" if parts else ""
    if struct_name == "Rotator" and isinstance(value, dict):
        parts = [f"{k}={value[k.lower()]}" for k in ("Pitch", "Yaw", "Roll")
                 if value.get(k.lower())]
        return "(" + ",".join(parts) + ")" if parts else "(Yaw=0)"
    if struct_name == "Color" and isinstance(value, dict):
        return _fmt_color(value)
    return ""  # undecodable struct -> skip


def _fmt_element(el) -> str:
    """Format a single array element as a T3D value ('' to omit it)."""
    if isinstance(el, ObjectRef):
        return "" if el.ref == 0 else el.qualified()  # engine omits null entries
    if isinstance(el, TaggedStruct):
        return _fmt_struct(el.struct_name, el)
    if isinstance(el, EnumValue):
        return el.name
    if isinstance(el, str):
        return f'"{el}"'
    if isinstance(el, float):
        return _fmt_float(el)
    return str(el)


def _fmt_prop_value(p) -> str:
    """Render one decoded Property as a T3D value, or '' to skip it."""
    t = p.type_id
    v = p.value
    if t == PROP_BOOL:
        return "True" if v else "False"
    if t in (PROP_INT, PROP_BYTE):
        return str(v)  # EnumValue stringifies to its bare identifier
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
    return ""  # Map / undecoded array / raw -> skip


def _bnum(v: float) -> str:
    if v == 0.0:
        v = 0.0  # normalize -0.0 -> +0.0 (matches the engine's T3D output)
    import decimal
    import math
    if not math.isfinite(v) or abs(v) >= 1e15:
        return f"{v:+013.6f}"
    d = decimal.Decimal(v).quantize(decimal.Decimal("0.000001"),
                                    rounding=decimal.ROUND_HALF_UP)
    return f"{d:+013.6f}"


def _bvec(v) -> str:
    return ",".join(_bnum(c) for c in v)


def _brush_lines(pkg: Package, brush_export: ExportEntry, props: list) -> list:
    """Emit the `Begin Brush … End Brush` polygon block for a Brush actor, or []
    if its Model/Polys can't be resolved (falls back to actor-only)."""
    model_ref = next((p.value.ref for p in props
                      if p.name == "Brush" and isinstance(p.value, ObjectRef)), 0)
    polys_ref = brush_polys_ref(pkg, model_ref)
    if not polys_ref:
        return []
    polys = decode_polys(pkg, polys_ref)
    if not polys:
        return []
    model_name = pkg.exports[model_ref - 1].object_name
    out = [f"    Begin Brush Name={model_name}", "       Begin PolyList"]
    for fp in polys:
        head = "          Begin Polygon"      # attribute order: Item, Texture, Flags, Link
        if fp.item and fp.item != "None":
            head += f" Item={fp.item}"
        if fp.texture.ref != 0:
            q = fp.texture.qualified()
            tex = q.split("'", 2)[1] if "'" in q else None
            if tex:
                head += f" Texture={tex}"
        if fp.flags:                      # engine emits Flags only when non-zero
            head += f" Flags={fp.flags & 0xFFFFFFFF}"
        if fp.link >= 0:                  # engine omits Link when -1 (unlinked)
            head += f" Link={fp.link}"
        out.append(head)
        out.append(f"             Origin   {_bvec(fp.base)}")
        out.append(f"             Normal   {_bvec(fp.normal)}")
        out.append(f"             TextureU {_bvec(fp.texture_u)}")
        out.append(f"             TextureV {_bvec(fp.texture_v)}")
        for v in fp.vertices:
            out.append(f"             Vertex   {_bvec(v)}")
        out.append("          End Polygon")
    out += ["       End PolyList", "    End Brush"]
    return out


def level_actor_order(pkg: Package):
    """Decode the Level ('myLevel') object's actor list: the authoritative actor
    ORDER for the map (CSG depends on brush sequence). Returns a list of export
    references (1-based), or None if unavailable."""
    lvl = next((e for e in pkg.exports if e.class_name == "Level"), None)
    if lvl is None or lvl.serial_size <= 0:
        return None
    try:
        r = Reader(pkg.raw, lvl.serial_offset)
        if r.compact_index() != 0:        # empty tagged-property list
            return None
        num = r.i32()
        r.i32()                           # Max
        if num < 0 or num > len(pkg.exports) * 2:
            return None
        refs = []
        for _ in range(num):
            v = r.compact_index()
            if 0 < v <= len(pkg.exports):
                refs.append(v)
        return refs or None
    except (IndexError, struct.error):
        return None


def to_t3d(pkg: Package, classes=None, clean: bool = False,
           saveable: bool = False, manifest: list = None) -> str:
    """Generate Map T3D. Whole-map output follows the Level object's actor list
    (the engine's CSG-relevant order, including no-Location actors like
    LevelInfo); class-filtered output falls back to placed-actor scanning.
    Emits the properties we can faithfully represent; engine-recomputed fields
    are skipped. With clean=True, also drops level-binding refs so the actors
    paste cleanly into an empty/other level. With saveable=True, omits refs to
    the source package's private/regenerable objects so the imported map can be
    SAVED as a new .ut2 (each omission is appended to `manifest`)."""
    skip = _T3D_SKIP_PROPS | _T3D_CLEAN_EXTRA if clean else _T3D_SKIP_PROPS
    order = None if classes else level_actor_order(pkg)
    if order is not None:
        # skip non-transactional (transient) actors, e.g. editor Cameras --
        # the engine's own T3D exporter omits them too
        kept = [ref for ref in order if pkg.exports[ref - 1].flags & 0x00000001]
        actors = [pkg.exports[ref - 1] for ref in kept]
    else:
        kept = []
        actors = pkg.exports
    ctx = None
    if saveable:
        ctx = {"actors": set(kept),
               "manifest": manifest if manifest is not None else []}
    lines = ["Begin Map"]
    for e in actors:
        if classes and e.class_name not in classes:
            continue
        props = read_properties(pkg, e)
        if order is None and not any(p.name == "Location" for p in props):
            continue
        lines.append(f"Begin Actor Class={e.class_name} Name={e.object_name}")
        _emit_props(pkg, e, props, lines, 4, skip, clean, ctx)
        lines.append("End Actor")
    lines.append("End Map")
    return "\n".join(lines)


RF_PUBLIC = 0x00000004

# LevelInfo metadata referencing the source map's private screenshot/summary
# objects; meaningless in a replica and re-set by hand in the editor if wanted.
_SAVEABLE_DROP_PROPS = {"Screenshot": "manual/cosmetic (LevelInfo screenshot)",
                        "Summary": "manual/cosmetic (LevelInfo summary)"}


def _saveable_drop(pkg: Package, ctx, ref: int):
    """In saveable mode: disposition string if a map-local object reference must
    be omitted so the saved map doesn't bind the source package's private or
    regenerable objects; None to keep (emitted actors and public assets)."""
    if ctx is None or ref <= 0:
        return None
    if ref in ctx["actors"]:
        return None                       # re-created actor: resolves locally
    e = pkg.exports[ref - 1]
    if e.class_name == "ReachSpec":
        return "auto-regenerated (Build AI Paths)"
    if not (e.flags & RF_PUBLIC):         # private map-local object
        if e.class_name == "StaticMeshInstance":
            return "auto-regenerated (Build Geometry/Lighting)"
        if e.class_name == "Model":
            return "auto-regenerated (CSG rebuild from inline brush polygons)"
        if e.class_name == "ConvexVolume":
            return "auto-regenerated (antiportal rebuild on Build Geometry)"
        return "manual/review (private map-local object)"
    return None                           # public asset (StaticMesh/Texture/...)


def _ref_str(pkg: Package, el: ObjectRef, ctx, inlined: bool = False) -> str:
    """Render an object reference. In saveable mode, refs to actors we emit (or
    sub-objects we inline) are qualified as MyLevel.<name> so the importer binds
    the locally created object instead of the loaded source package's private
    one (which would block saving)."""
    if el.ref == 0:
        return "None"
    if ctx is not None and el.ref > 0 and (el.ref in ctx["actors"] or inlined):
        e = pkg.exports[el.ref - 1]
        return f"{e.class_name}'MyLevel.{e.object_name}'"
    return el.qualified()


def _log_omission(ctx, e: ExportEntry, prop: str, target: ExportEntry,
                  disposition: str) -> None:
    ctx["manifest"].append({
        "actor": e.object_name, "actor_class": e.class_name,
        "property": prop, "omitted": target.object_name,
        "omitted_class": target.class_name, "disposition": disposition,
    })


def _emit_props(pkg: Package, e: ExportEntry, props: list, lines: list,
                indent: int, skip, clean: bool, ctx=None) -> None:
    """Emit one object's properties as T3D lines (recurses into sub-objects)."""
    pad = " " * indent
    owner_ref = pkg.exports.index(e) + 1
    for p in props:
        if p.name in skip:
            continue
        if ctx is not None and p.name in _SAVEABLE_DROP_PROPS \
                and isinstance(p.value, ObjectRef) and p.value.ref > 0:
            _log_omission(ctx, e, p.name, pkg.exports[p.value.ref - 1],
                          _SAVEABLE_DROP_PROPS[p.name])
            continue
        if ctx is not None and p.name == "Region":
            # derived zone binding (Zone=ZoneInfo'<source-pkg>...'); recomputed
            # on Build Geometry -- dropping avoids cross-package actor refs
            zone = p.value.get("Zone") if isinstance(p.value, dict) else None
            tgt = pkg.exports[zone.ref - 1] if isinstance(zone, ObjectRef) \
                and zone.ref > 0 else e
            _log_omission(ctx, e, "Region", tgt,
                          "auto-regenerated (zones recomputed on Build Geometry)")
            continue
        if p.type_id == PROP_ARRAY and isinstance(p.value, list):
            # arrays declared with the 'export' modifier (e.g. Emitter.Emitters)
            # inline their Begin Object blocks first, then the array lines,
            # then a blank line
            inline = (not clean and p.name in schema().get("export_arrays", ()))
            for idx, el in enumerate(p.value):  # one line per element
                if (inline and isinstance(el, ObjectRef) and el.ref > 0
                        and pkg.exports[el.ref - 1].outer_ref in (owner_ref, 0)):
                    # interleave: Begin Object block, the array line, blank
                    se = pkg.exports[el.ref - 1]
                    lines.append(f"{pad}Begin Object Class={se.class_name} "
                                 f"Name={se.object_name}")
                    _emit_props(pkg, se, read_properties(pkg, se), lines,
                                indent + 4, skip, clean, ctx)
                    lines.append(f"{pad}End Object")
                    lines.append(f"{pad}{p.name}({idx})="
                                 f"{_ref_str(pkg, el, ctx, inlined=True)}")
                    lines.append("")
                    continue
                if isinstance(el, ObjectRef):
                    disp = _saveable_drop(pkg, ctx, el.ref)
                    if disp:
                        _log_omission(ctx, e, f"{p.name}({idx})",
                                      pkg.exports[el.ref - 1], disp)
                        continue
                    es = "" if el.ref == 0 else _ref_str(pkg, el, ctx)
                else:
                    es = _fmt_element(el)
                if es:
                    lines.append(f"{pad}{p.name}({idx})={es}")
            continue
        if p.name == "Brush" and not clean:
            # engine layout: inline polygon block, then the Brush= line,
            # then a blank line
            geo = _brush_lines(pkg, e, props)
            if geo:
                lines.extend(geo)
                if ctx is not None and isinstance(p.value, ObjectRef) \
                        and p.value.ref > 0:
                    # bind to the inline model in the LOCAL level package (what
                    # UnrealEd's own copy/paste emits) instead of the source
                    # package -- the Brush= line is what attaches the model,
                    # so it must not be dropped (Actors(1)->Brush!=NULL assert)
                    target = pkg.exports[p.value.ref - 1]
                    _log_omission(ctx, e, "Brush", target,
                                  "rewritten -> Model'MyLevel."
                                  f"{target.object_name}' (binds inline model; "
                                  "no action needed)")
                    lines.append(f"{pad}Brush=Model'MyLevel.{target.object_name}'")
                    lines.append("")
                    continue
                lines.append(f"{pad}Brush={_fmt_prop_value(p)}")
                lines.append("")
                continue
        if isinstance(p.value, ObjectRef):
            disp = _saveable_drop(pkg, ctx, p.value.ref)
            if disp:
                _log_omission(ctx, e, p.name, pkg.exports[p.value.ref - 1], disp)
                continue
            s = _ref_str(pkg, p.value, ctx) if ctx is not None \
                else _fmt_prop_value(p)
        else:
            s = _fmt_prop_value(p)
        if not s:
            continue
        if p.array_index or p.name in schema().get("static_arrays", ()):
            key = f"{p.name}({p.array_index})"   # static arrays always indexed
        else:
            key = p.name
        lines.append(f"{pad}{key}={s}")
        if e.class_name == "Mover":
            # the engine prints these native sentinels on every Mover, in
            # class-declaration order: BasePos, SavedPos, ..., BaseRot, SavedRot
            if p.name == "BasePos":
                lines.append(f"{pad}SavedPos=(X=-12345.000000,Y=-12345.000000,"
                             f"Z=-12345.000000)")
                if not any(q.name == "BaseRot" for q in props):
                    lines.append(f"{pad}SavedRot=(Pitch=123,Yaw=456,Roll=789)")
            elif p.name == "BaseRot":
                lines.append(f"{pad}SavedRot=(Pitch=123,Yaw=456,Roll=789)")


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
    ap.add_argument("--t3d-saveable", action="store_true",
                    help="with --t3d, omit private/regenerable source-package refs so the "
                         "imported map can be saved; writes <map>_omissions.json/.log")
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
            manifest = []
            print(to_t3d(pkg, classes=set(args.t3d_class) if args.t3d_class else None,
                         clean=args.t3d_clean, saveable=args.t3d_saveable,
                         manifest=manifest))
            if args.t3d_saveable:
                stem = os.path.splitext(os.path.basename(path))[0] + "_omissions"
                with open(stem + ".json", "w") as fh:
                    json.dump(manifest, fh, indent=1)
                with open(stem + ".log", "w") as fh:
                    fh.write(f"Omissions manifest for {path} (saveable T3D mode)\n")
                    fh.write(f"{len(manifest)} references omitted\n\n")
                    bycat = {}
                    for m in manifest:
                        bycat.setdefault(m["disposition"], []).append(m)
                    for disp, items in sorted(bycat.items()):
                        fh.write(f"== {disp} == ({len(items)})\n")
                        for m in items:
                            fh.write(f"  {m['actor_class']} {m['actor']}."
                                     f"{m['property']} -> {m['omitted_class']}"
                                     f"'{m['omitted']}'\n")
                        fh.write("\n")
                import sys as _sys
                print(f"[saveable] {len(manifest)} omissions -> {stem}.json/.log",
                      file=_sys.stderr)
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
