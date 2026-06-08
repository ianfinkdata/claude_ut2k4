# UT2004 DM Map Project — Context

## Goal
Read, interpret, and ultimately reconstruct UT2004 official Deathmatch maps, with the
longer-term aim of programmatically generating/modifying maps. Scope is intentionally
limited to **official UT2004 DM maps** (the stock maps shipped with the game), not custom
community content.

## Repo contents
- `.ut2` files: official UT2004 Deathmatch maps (binary Unreal packages).

---

## File format essentials

All UT2004 content files share **one format** — the Unreal package format. The extension
(`.ut2` map, `.utx` texture, `.usx` static mesh, `.uax` sound, `.u` compiled code) is
organizational only; the binary structure is identical across all of them.

- **Magic signature:** `0x9E2A83C1` at offset 0. Use it to validate, not the extension.
- **Engine:** Unreal Engine 2 / package version in the ~119–129 range for UT2004.
- **Layout:** Header → Name Table → Import Table → Export Table → serialized object data.
  - **Header:** signature, version, flags, GUID, and the counts + file offsets for each table.
  - **Name Table:** all unique strings (object/class/reference names); the tables and
    objects reference names by index into this table rather than storing strings inline.
  - **Import Table:** objects this package depends on from *other* packages.
  - **Export Table:** every object defined *in* this package, with class, offset, and size.
  - **Object data:** tagged-property serialization — `name → type → size → value` per
    property — for each exported object.

### Two encoding details that bite
- **Compact Index:** signed 32-bit values stored in 1–5 bytes; sign + 6 value bits in the
  first byte, 7 bits per subsequent byte. Used everywhere (array lengths, name/object refs).
  Must be decoded correctly before anything else parses.
- **Arrays:** prefixed with a compact-index length, then that many elements of the array type.

### What parses cleanly vs. what's hard
- **Reliable:** header, name table, import/export tables, and standard tagged properties
  on actors — classes, locations, rotations, scales, common settings. Enough to enumerate
  every actor in a map and its dependencies.
- **Hard / not fully public:** BSP tree, brush polys, lightmaps, terrain heightmaps. A
  generic parser extracts the metadata and actor list but can't always fully decode these
  geometry blobs.

---

## Architecture decision: read binary, write via T3D

**Do not hand-author binary `.ut2` files.** Producing a map the engine will load requires
reproducing internal UnrealEd work (CSG/BSP rebuild, node generation, lighting bake,
path-node networks). A raw binary writer is far too fragile.

**Pipeline:**
1. **Read / interpret:** parse the binary `.ut2` directly (Python). Recover header, names,
   tables, and actor properties.
2. **Write / modify:** generate or transform **T3D** (UnrealEd's plain-text export format —
   actors, brushes with full polygon defs, properties). UnrealEd *imports* T3D and rebuilds
   geometry from it.
3. **Finalize in-engine:** in UnrealEd, Build Geometry → Build Lighting → save as `.ut2`.
   The engine does the hard serialization.

Text in/out for the logic; the engine for the binary.

---

## Reference resources
- **shrimpza/unreal-package-lib** (GitHub, Java) — reads/exports UE1/2/3 packages, tested
  against UT2004. Best reference implementation for compact-index decoding, table walking,
  and tagged-property reading. Known limitation: no UnrealScript class reading; meshes need
  extra reader implementations. Model the Python parser on this.
- **BeyondUnreal Wiki — "Unreal package" / "Package File Format"** — header, tables,
  compact index, data types.
- **EliotVU — "Unreal Package File Format"** — additional header/format detail.
- **Unreal Archive (unrealarchive.org)** — hash-verified map preservation. Out of scope
  (custom maps) but useful as a format/sample reference if needed.

### Note on distribution format
Community maps often ship compressed as `.uz2` and need `ucc decompress` (or UT2004MI)
back to `.ut2`. Stock official maps are already plain `.ut2` in the game's `Maps/` folder.

---

## Suggested first steps in Claude Code
1. Write a Python `.ut2` parser: validate magic, read header, decode compact index,
   walk name/import/export tables. Print a summary (package version, counts, name list).
2. Run it against one official DM map; confirm the actor/object list comes out cleanly.
3. Iterate to decode standard actor properties (location/rotation/scale/class).
4. Only then move to T3D generation for the write side.
