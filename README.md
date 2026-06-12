# UT2004 DM Map Project

Reading, interpreting, and reconstructing official **UT2004 Deathmatch** maps — with the
longer-term goal of programmatically generating/modifying them. Scope is the 39 stock DM
maps shipped with the game (binary `.ut2` Unreal packages).

**Project report (GitHub Pages):** https://ianfinkdata.github.io/claude_ut2k4/

## Architecture

*Read binary, write via T3D.* Hand-authoring binary `.ut2` files is too fragile — instead:

1. **Read** — parse the binary `.ut2` directly in Python (`ut2parser.py`).
2. **Write** — generate/modify **T3D** (UnrealEd's plain-text export format).
3. **Finalize** — import the T3D into UnrealEd, Build Geometry → Build Lighting → save `.ut2`.

## Repo map

- `Maps/` — 39 stock UT2004 DM maps (`.ut2`, binary Unreal packages).
- `ut2parser.py` — binary reader, property decoder, JSON model, diff, T3D generator.
- `schema_extractor.py` / `schema.json` — class schema (enums/arrays) extracted from the
  game's UnrealScript.
- `navanalysis.py` / `NAV_PATTERNS.md` — bot-pathing & inventory pattern analysis across
  all maps.
- `import_kit/` — UnrealEd import kit (clean T3D subsets + paste instructions).
- `replica/` — a fully replicated, engine-verified map (`DM-Rankin-Replica.ut2`).
- `docs/` — source for the [GitHub Pages report](https://ianfinkdata.github.io/claude_ut2k4/).
- `CLAUDE.md` — durable project context & file-format notes.
- `PROGRESS.md` — status, findings, and roadmap.

## Quick start

```sh
python ut2parser.py Maps/DM-Rankin.ut2              # summarize one map
python ut2parser.py Maps/DM-Gael.ut2 --actors       # placed actors w/ location+rotation
python ut2parser.py Maps/DM-Rankin.ut2 --t3d > out.t3d   # generate full-map T3D

python navanalysis.py Maps/*.ut2                    # bot-path/inventory report
```

See [PROGRESS.md](PROGRESS.md) for full details and [CLAUDE.md](CLAUDE.md) for format notes.

## License

GPLv3 — see [LICENSE](LICENSE).
