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
skills, untouched; `--replace` swaps only known targets. `--home <dir>` installs into another home.

## Tools

| Tool | Does |
|---|---|
| `codemap.py find` | every existing definition of a concept across linked checkouts, duplicates first |
| `catalog.py` | add, search and resolve `docs/issues/` entries |
| `re_frontier.py` | the ordered RE steps in `docs/re-frontier.md`: what is ready, what is hack debt |
| `cpp_policy.py` | AST scan for global functions, `extern`, block statics, stray `main` and retired calls; `--help` |
| `go_public.py` | history audit before a repo goes public |
| `scratch_gc.py` | sweep a repo's `scratch/` |
| `cleanup-files` | remove an explicit list of in-tree files |
| `play_api.py`, `play_console.py` | Google Play tracks and uploads; the console web UI through WebLua |

The tools read project data from the working project (`docs/issues/`, `docs/re-frontier.md`,
source), never from this repo.
