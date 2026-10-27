# Shared agent configuration repository

This checkout is the one editable source of the global instructions (`instructions/AGENTS.md`), the
skills (`skills/<scope>/<name>/SKILL.md`) and the shared tools (`tools/`). Agent homes and
`~/repo/AGENTS.md` hold links into it; edit here, never through an installed path.

- Skill scopes and names: `skills/README.md`. Module map: `docs/codemap.md`.
- A skill package links to its tool in `tools/`; it never carries a copy.
- `tools/install_skills.py` is the only installer:
  `uv run --no-project python tools/install_skills.py install --replace`, then `check`.
