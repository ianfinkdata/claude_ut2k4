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


def parse(data: bytes) -> Package:
    r = Reader(data)
    magic = r.u32()
    if magic != MAGIC:
        raise ParseError(
            f"bad magic 0x{magic:08X} (expected 0x{MAGIC:08X}); not an Unreal package"
        )

    pkg = Package()
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


def main(argv: list) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Parse and summarize UT2004 .ut2 packages")
    ap.add_argument("files", nargs="+", help=".ut2 (or other Unreal package) files")
    ap.add_argument("--top", type=int, default=25, help="how many top classes to show")
    args = ap.parse_args(argv)

    for path in args.files:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            pkg = parse(data)
        except ParseError as exc:
            print(f"== {path} ==\n  ERROR: {exc}\n")
            continue
        print(_summary(path, pkg, args.top))
        print()
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
