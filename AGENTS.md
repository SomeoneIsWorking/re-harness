# Shared agent-skills repository

This repository is the canonical source for the user's portable skills and
their reusable CLIs. Installed agent homes contain symlinks into this checkout;
do not edit installed copies as separate authorities.

## Information

- Epic intent: `docs/project-goals.md`
- Factual capability coverage: `docs/project-state.md`
- Ownership and placement: `docs/codemap.md`
- Atomic issues: `docs/issues/` when needed

Run `python3 tools/project_state.py --root .` after changing project state or
cross-links. Run `python3 tests/run.py` after changing a shared CLI or installer.

## Skill ownership

- `skills/global/`: project-agnostic workflow and hygiene skills.
- `skills/port/`: port architecture shared by recomp and non-recomp ports.
- `skills/re/`: binary/asset reverse-engineering workflows.
- `skills/recomp/`: static-recompiler-specific workflows.

Each skill owns one `SKILL.md` package. Reusable CLI implementations live once
under `tools/`; a skill package may symlink to its tool. Root-level tool names
are stable compatibility symlinks for existing consumers.

Add a new category only for a real applicability boundary. Do not classify a
skill as recomp-specific merely because its first consumer is a recomp project.

## Installation

`tools/install_skills.py` is the only installer. It links every skill into
`.agents/skills`, `.codex/skills`, and `.claude/skills` under the selected home.
It must never touch `.codex/skills/.system` or replace an unrelated directory.
