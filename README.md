# Shared agent configuration

This repository is the portable source of truth for the user's global instructions, reusable agent
skills, and shared command-line tools. The checkout retains its
historical `re-harness` repository name so existing consumers and remote URLs do
not break; its scope is now broader than reverse engineering.

## Structure

| Directory | Applicability |
|---|---|
| `instructions/` | One global instruction authority for every supported agent |
| `skills/global/` | Any long-lived project or repository |
| `skills/port/` | Game-port architecture, independent of guest execution strategy |
| `skills/re/` | Ground-truth recovery from binaries, assets, emulators, or engines |
| `skills/dynarec/` | Runtime interpretation, dynamic translation, overrides, and differential verification |
| `tools/` | One authoritative implementation of reusable CLIs |
| `tests/` | Positive and negative controls for the shared instruments |

See [`skills/README.md`](skills/README.md) for the complete skill taxonomy and
[`docs/codemap.md`](docs/codemap.md) for ownership and placement.

## Install agent links

The installer links the global instruction file, every categorized skill, and every public shared
tool into the supported locations under the selected home directory:

```text
python3 tools/install_skills.py install --replace
python3 tools/install_skills.py check
```

It creates relative symlinks in `.agents`, `.codex`, `.claude`, and `~/repo/AGENTS.md`. It leaves
unrelated entries, including Codex's `.system` skills, untouched. `--replace` is required to migrate
an existing known target and still refuses unrelated skill directories.

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
| `tools/cleanup-files` | How to remove an explicit set of in-tree files without partial cleanup |
| `tools/safekill` | How to terminate an exact process without matching the calling shell |
| `tools/swarm.py` | Which bounded jobs a free LLM worker completed that a scripted gate accepted (`swarmkit/` owns worktrees, backends, slots, verdicts) |

`tools/cpp_policy.py` checks first-party C++ global functions, `extern`
declarations, and function-local `static` variables against Clang's AST from a
real compile database. A local `const` or `constexpr` is not a finding: it is
the recommended way to write a local, and flagging it buried the real ownership
findings under a hundred good ones.

Each unit is parsed in-process by the libclang that ships beside the compile
command's Clang driver (`tools/libclang_ast.py`, a ctypes binding, so no Python
package is needed), and the walk enters only file-scope declarations that expand
in first-party files: system and library headers are parsed by Clang and never
visited from Python. A missing or mismatched libclang is refused with the
install command for each platform; no other libclang is substituted. Units are
scanned in separate processes using every core unless `CPP_POLICY_JOBS` says
otherwise.

Each unit's result is cached under `<compile database dir>/cpp_policy_cache/`
(`tools/unit_cache.py`), keyed by the compile command, libclang version, tool
sources and scan options, and valid only while every file that parse read
(Clang's own inclusion list) has the same content hash and every first-party
include directory and includer directory has the same file listing, so a new
header that shadows a read one or satisfies a `__has_include` rescans the unit.
An unchanged tree re-gates in seconds; a header edit rescans only the units that
include it, and an added or removed file rescans the units that search its
directory. A result whose inputs changed after its parse started is not stored.
New files in system or other non-first-party include directories are not watched.
Invoke it from a project's normal verifier alongside clang-tidy and
clang-format:

```text
python3 tools/cpp_policy.py --audit-config .
python3 tools/cpp_policy.py --root . --compile-commands build/debug/compile_commands.json --exclude third_party
```

A port that already has ownership it cannot unpick in one change names those
sites in a file and passes `--accept`, one `path:rule:symbol` per line with the
reason above it. That turns the scan into a ratchet: what is named passes, and
anything new fails. There is no line number in a site, so it survives edits to
the file above it, and an accepted site that stops occurring is reported as a
violation of its own — an allowance nobody removes when the code improves is
how a gate quietly stops covering the thing it was written for.

The config audit reads the effective `.clang-tidy` and `.clang-format` settings
with the installed Clang tools and refuses disabled defaults or missing brace
rules. It does not rewrite a project's policy.

Use `--exclude` only for exact vendored/generated subtrees and `--allow-global`
only for documented platform entry points; `main` and real `extern "C"`
functions are recognized automatically. A GCC compile command is parsed with
the libclang of the matching Clang driver.

`--entry-root` (repeatable, a file or subtree) turns on the `entry point` rule:
`main` is then allowed only inside an entry root, and a `main` anywhere else is
reported as `path:entry point:main`. A project with one framework-owned `main`
passes that file plus its `tests/` and `tools/` trees, and lists each remaining
hand-written `main` in its `--accept` file until it is folded in. Without
`--entry-root`, `main` is an entry point wherever it is. The tool reports the translation-unit
and first-party file counts even when it finds no violations.

`--retired-name NAME` (repeatable) reports every first-party reference to the named function outside
the entry roots as `path:retired name:NAME`. References are resolved from the AST, so a comment, a
string or a same-named member does not count, and a declaration in an excluded header still does. It is
for a framework step a project now composes once, so a title that re-adds the call fails; harnesses
under the entry roots may still drive it.

Claim staleness needs complete Git history because its symbol evidence comes from `git log -L`.
`tools/info.py claim check` refuses shallow repositories; CI checkouts must fetch full history (for
`actions/checkout`, use `fetch-depth: 0`) rather than treating a shallow boundary as a code change.

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

The test suite exercises both positive and negative controls, including an isolated global
instruction/skill/tool installation. An empty corpus cannot masquerade as a successful search.
