# Shared agent configuration

The portable source of the user's global agent instructions, skills and shared command-line tools.

| Directory | Holds |
|---|---|
| `instructions/` | the global instructions every agent reads |
| `skills/` | skill packages by scope; see [`skills/README.md`](skills/README.md) |
| `tools/` | the shared CLIs, one implementation each |
| `docs/` | this repo's goals, state and [module map](docs/codemap.md) |

## Install

```text
uv run --no-project python tools/install_skills.py install --replace
uv run --no-project python tools/install_skills.py check
```

The installer links the instructions, every skill and every tool in `TOOL_NAMES` into `.agents`,
`.codex`, `.claude`, `~/.local/bin` and `~/repo/AGENTS.md` as relative symlinks, and removes links
to skills and tools that no longer exist. It leaves unrelated entries, including Codex's `.system`
skills, untouched; `--replace` swaps only known targets. `--home <dir>`, before the subcommand, installs into another home.

## Tools

One implementation each; those in `TOOL_NAMES` are linked onto `PATH` by the installer. What each owns is in
[`docs/codemap.md`](docs/codemap.md). They read project data from the working project
(`docs/issues/`, `docs/re-frontier.md`, source), never from this repo.

Built with AI assistance (Claude and other LLMs).
