# Shared agent configuration repository

This repository is the canonical source for the user's portable global instructions, skills, and
reusable CLIs. Agent homes and `~/repo/AGENTS.md` contain symlinks into this checkout; do not edit
installed paths as separate authorities.

## Information

- Epic intent: `docs/project-goals.md`
- Factual capability coverage: `docs/project-state.md`
- Ownership and placement: `docs/codemap.md`
- Atomic issues: `docs/issues/` when needed

Run `python3 tools/project_state.py --root .` after changing project state or
cross-links. Run `python3 tests/run.py` after changing a shared CLI or installer.

## Skill ownership

- `skills/global/`: project-agnostic workflow and hygiene skills.
- `skills/port/`: port architecture independent of guest execution strategy.
- `skills/re/`: binary/asset reverse-engineering workflows.
- `skills/dynarec/`: runtime guest execution and dynamic-translation workflows.

Each skill owns one `SKILL.md` package. Reusable CLI implementations live once
under `tools/`; a skill package may symlink to its tool. Root-level tool names
are stable compatibility symlinks for existing consumers.

Add a new category only for a real applicability boundary. Do not classify a
skill as dynarec-specific merely because its first consumer is a runtime-translated port.

## Installation

`tools/install_skills.py` is the only installer. It links the global instruction file, every skill,
and every public shared tool into `.agents`, `.codex`, and `.claude`, plus the `~/repo` instruction
scope. It must never touch vendor-owned files or replace an unrelated directory.
