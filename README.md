# Shared agent skills

This repository is the portable source of truth for the user's reusable agent
skills and the command-line tools those skills share. The checkout retains its
historical `re-harness` repository name so existing consumers and remote URLs do
not break; its scope is now broader than reverse engineering.

## Structure

| Directory | Applicability |
|---|---|
| `skills/global/` | Any long-lived project or repository |
| `skills/port/` | Game-port architecture, independent of recomp/decomp strategy |
| `skills/re/` | Ground-truth recovery from binaries, assets, emulators, or engines |
| `skills/recomp/` | Whole-binary static-recompiler workflows |
| `tools/` | One authoritative implementation of reusable CLIs |
| `tests/` | Positive and negative controls for the shared instruments |

See [`skills/README.md`](skills/README.md) for the complete skill taxonomy and
[`docs/codemap.md`](docs/codemap.md) for ownership and placement.

## Install agent discovery links

The installer links every categorized skill into the supported discovery roots
under the selected home directory:

```text
python3 tools/install_skills.py install --replace
python3 tools/install_skills.py check
```

It creates relative directory symlinks in `.agents/skills`, `.codex/skills`,
and `.claude/skills`. It leaves unrelated entries, including Codex's `.system`
skills, untouched. `--replace` only accepts a same-named skill package with a
matching `SKILL.md`; it refuses unrelated directories.

Use `--home <directory>` before the subcommand to test an isolated installation.
Editing an installed path edits this checkout through the symlink, so there is
no second mutable copy to drift.

## Shared information tools

| Tool | Answers |
|---|---|
| `tools/info.py` | What has been proven, falsified, or measured, and whether the evidence is stale |
| `tools/project_state.py` | Whether goals, factual project state, and issue links form a coherent graph |
| `tools/catalog.py` | Which atomic tasks, bugs, findings, blockers, and dead ends have been recorded |
| `tools/codemap.py` | Whether source coverage and subsystem placement are mapped |
| `tools/re_frontier.py` | Which ordered RE step is ready and which steps carry hack debt |
| `tools/go_public.py` | Which history entries contain material that must not ship publicly |
| `tools/safekill` | How to terminate an exact process without matching the calling shell |

The root names `info.py`, `catalog.py`, `re_frontier.py`, and
`project_state.py` are compatibility symlinks for existing consumers. New
integrations should invoke `tools/` directly.

These tools resolve project data from the working project, not from this
repository. The data remains with that project:

- `docs/project-goals.md` — epic-level intent;
- `docs/project-state.md` — factual capability and outcome coverage;
- `docs/issues/` — atomic work and investigation history;
- `docs/codemap.md` — subsystem ownership and placement;
- `docs/info/` — evidence claims and instrument trust;
- `docs/re-frontier.md` — specialized RE dependency ordering.

## Verify changes

Run the complete local gate from this checkout:

```text
python3 tests/run.py
python3 tools/project_state.py --root .
```

The test suite exercises both positive and negative controls, including an
isolated three-root skill installation. An empty corpus cannot masquerade as a
successful search.
