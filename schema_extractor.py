#!/usr/bin/env python3
"""Extract class schema (enum value lists + array inner-types) from UnrealScript.

The tagged-property stream in a `.ut2` package does NOT carry enough type info to
fully decode enum bytes (we only get the numeric index) or dynamic arrays (the
element type lives in the class definition, not the stream). This tool recovers
that metadata from the engine's own UnrealScript, exported with:

    ucc batchexport Engine.u Class UC <dir>     (repeat for other packages)

It parses every `.uc` file and emits a compact `schema.json`:
  - enum_props:  property name -> ordered list of enum value names (so byte N -> name)
  - array_props: property name -> inner type string (so arrays can be sub-decoded)

Property names are keyed globally; that's imprecise in theory but fine in practice
for the handful of props that appear in stock DM-map actors.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# enum  EName { V0, V1, ... }  [optional trailing var name]  ;
_ENUM_RE = re.compile(r"\benum\s+(\w+)\s*\{([^}]*)\}\s*(\w*)\s*;", re.DOTALL)
# var(...) <modifiers> array<Inner>  Name ;
_ARRAY_RE = re.compile(r"\bvar\b[^;{}]*?\barray\s*<\s*(\w+)\s*>\s*(\w+)\s*;")
# var(...) <modifiers> TypeName Name ;   (for vars typed by a standalone enum)
_SIMPLEVAR_RE = re.compile(r"\bvar\b(?:\s*\([^)]*\))?\s+([\w ]+?)\s+(\w+)\s*;")


def _enum_values(body: str) -> list:
    vals = []
    for line in body.splitlines():
        line = re.sub(r"//.*$", "", line)             # strip line comment
        line = line.split(",")[0].strip().rstrip(",")  # first token before comma
        if re.fullmatch(r"[A-Za-z_]\w*", line):
            vals.append(line)
    return vals


def extract(uc_dir: str) -> dict:
    enum_defs: dict = {}     # EnumName -> [values]
    enum_props: dict = {}    # propName -> EnumName
    array_props: dict = {}   # propName -> inner type

    files = sorted(Path(uc_dir).glob("*.UC")) + sorted(Path(uc_dir).glob("*.uc"))
    for fp in files:
        text = fp.read_text(errors="replace")

        for m in _ENUM_RE.finditer(text):
            ename, body, trailing_var = m.group(1), m.group(2), m.group(3)
            vals = _enum_values(body)
            if vals:
                enum_defs[ename] = vals
            if trailing_var:                       # inline:  enum E {...} Prop;
                enum_props[trailing_var] = ename

        for m in _ARRAY_RE.finditer(text):
            inner, name = m.group(1), m.group(2)
            array_props.setdefault(name, inner)

        # vars typed by an enum *name* (e.g. `var ECsgOper CsgOper;`)
        for m in _SIMPLEVAR_RE.finditer(text):
            typ, name = m.group(1).split()[-1], m.group(2)
            if typ in enum_defs or typ.startswith("E"):
                enum_props.setdefault(name, typ)

    # resolve prop -> enum NAME into prop -> value LIST (drop unresolved)
    resolved_enum_props = {
        prop: enum_defs[en] for prop, en in enum_props.items() if en in enum_defs
    }

    return {
        "enum_props": dict(sorted(resolved_enum_props.items())),
        "array_props": dict(sorted(array_props.items())),
        "_enum_defs_count": len(enum_defs),
    }


def main(argv: list) -> int:
    if len(argv) < 1:
        print("usage: schema_extractor.py <uc_dir> [<uc_dir>...] -o schema.json",
              file=sys.stderr)
        return 2
    out = "schema.json"
    dirs = []
    it = iter(argv)
    for a in it:
        if a == "-o":
            out = next(it)
        else:
            dirs.append(a)

    merged = {"enum_props": {}, "array_props": {}}
    total_enums = 0
    for d in dirs:
        s = extract(d)
        merged["enum_props"].update(s["enum_props"])
        merged["array_props"].update(s["array_props"])
        total_enums += s["_enum_defs_count"]

    Path(out).write_text(json.dumps(merged, indent=1))
    print(f"{out}: {len(merged['enum_props'])} enum props, "
          f"{len(merged['array_props'])} array props "
          f"(from {total_enums} enum defs across {len(dirs)} dir(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
