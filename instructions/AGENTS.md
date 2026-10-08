# Global working principles

`shared/re-harness` is the only editable source of these instructions, the skills and the shared
`tools/`; agent homes and `~/repo/AGENTS.md` are links installed by `tools/install_skills.py`.
Domain rules live in skills: CI, releases and Android for any product in `release` and `android`;
game ports add `dynarec-port`, `game-port-structure` and `port-release`.

## How to work a problem

Every bug, regression or feature follows these steps in order. Skipping one is how bandaids happen.

1. **Reproduce.** Write down observed vs expected and the exact input that shows it (replay and
   frame, warp target, command). No reproduction, no change.
2. **Find the owner.** `docs/codemap.md` to the module; read its doc and the code path end to end
   before editing anything. If the codemap cannot lead you there, fix the codemap first.
3. **Trace to the cause.** Follow the wrong value back to where it first goes wrong; for guest
   behaviour, decompile the guest function. Write the cause as one sentence naming `file:function`.
   Until you can, you are still investigating: read, log, bisect; do not edit product code.
4. **Fix at the owner.** The smallest change that makes the owner correct. If the owner's
   structure cannot express the fix cleanly, restructure it first (its own commit), then fix.
5. **Prove it.** A unit test through the shipping code that fails before and passes after, and the
   reproduction now showing the expected behaviour.
6. **Record it.** Update the owner's doc where the contract or behaviour changed.

If a fix does not work, revert it and go back to step 3; never stack a second guess on the first.
These are bandaids, not fixes: a magic offset, a branch or flag for the failing input, a swallowed
error, `|| true`, retry-until-pass, a sleep for a race, a skipped check, a hardcoded expected value,
a second implementation beside the first, anything "for now". If the real fix is too big, say so,
name the proper fix and the stopgap's risk, and let the user decide; an approved stopgap is marked
`// STOPGAP: <proper fix> because <why>`.

## Docs

- Each subsystem has one doc a new developer can work from: what it owns, inputs and outputs,
  invariants, data flow, how to test it. Keep it accurate; it is what makes step 2 possible.
- `docs/codemap.md` says where code lives. Read it before placing code; update it in the change that
  adds or moves an owner.
- `docs/project-goals.md`: stable goal IDs, outcomes, success conditions, non-goals.
- `docs/project-state.md`: every intended capability as `verified`/`partial`/`blocked`/`missing`
  with evidence or the exact gap, one current focus, and a comparison baseline listing each
  user-visible delta from the original (widescreen, loading, controls, platforms, ...).
- `docs/issues/`: one bug, task or dead end per file. `docs/re-frontier.md`: what has and has not
  been reverse-engineered; update it in the same commit as the RE work.
- Write what you learn into the owning doc in the same session; fix a wrong note rather than adding
  another. Agent memory holds only cross-project preferences.
- Comments and docs read like a developer wrote them. A comment is one short line where the code
  cannot speak: a reason, a hardware fact, a guest address. No paragraphs, no history or measurement
  narration, no restating the code, no shouting caps. Delete such prose on sight.

## Communication

- Be brutally honest. No flattery or affirmation openers; if the user is wrong on fact or logic, say
  so plainly and proceed correctly.
- The user's observation of the running product outranks your evidence. Treat a reported regression
  as a falsifier and reproduce from the last known-good state.
- Report delivery state literally: subagent report, dirty tree, local commit and pushed commit are
  different states. "Done" means integrated, gated, committed and pushed.
- Do what was asked. Suggest a better idea; do not substitute it.
- For an irreversible step, name the exact consequence. Do it if authorized; otherwise ask once.

## Code

- One owner per concept: focused modules and classes with explicit dependencies; entry points only
  compose. New behaviour goes in the smallest owning module; split a touched monolith at the relevant
  boundary before extending it. No `Utils`/`Manager`/`Common`/`Misc`, numbered fragments or
  forwarding webs.
- One implementation of each rule, formula, parser, state transition and mapping. Search for the
  owner before adding code. Tests exercise the shipping code through a seam, never a copy.
- No dead code, stale names, warnings or compatibility paths once their replacement exists.
- Errors preserve valid state: fail fast or propagate; catch only to restore an invariant, add
  context, retry an idempotent operation, or terminate cleanly.
- The project verifier fails on source files over 1,200 lines, growth of known monoliths, forbidden
  cross-layer dependencies, output outside the logger, and environment reads outside the config
  owner. Limits only shrink.
- Reusable title-neutral C++ helpers go in Lucent, tested there.

## C++

- Agents build with Clang and confirm `CMAKE_CXX_COMPILER_ID=Clang`; projects keep building with
  GCC, AppleClang and other supported compilers. If Clang cannot build a project, report it.
- Tracked `.clang-format` (every body braced, one statement per line) and `.clang-tidy` (defaults plus
  `clang-analyzer-*`, `bugprone-*`, `performance-*`, braces; warnings are errors), both checked by
  the verifier; copy them from a maintained repo. Fix findings; never blanket-suppress.
- State lives in classes in project namespaces with RAII; no project functions in the global
  namespace, no C facade over a class, no `extern` globals, no function-local `static`. Declarations
  live in the owning header; constants are `inline constexpr` there. `tools/cpp_policy.py` enforces
  what clang-tidy cannot.
- Logging goes through Lucent only, one line per call, never wrapped in `if`. One config owner reads
  the environment into typed immutable config; nothing else calls `getenv`. Local HTTP and control
  channels use `lucent::http::Server`.

## Tooling

- `./run.sh` launches the one intended product with zero arguments and is the fresh-clone setup
  path; it is a shim (`exec uv run --frozen python bootstrap.py "$@"`). Agents never run it; verify
  with headless, silent maintainer tools that reuse the same build modules.
- Python runs in one locked environment (`pyproject.toml`/`uv.lock`, `uv run --frozen`); a bare
  `python3` in project tooling is a defect. Project tooling is modular Python, not shell.
- A missing native package gets a refusal naming the exact install command per platform.
- Provision missing tools yourself without root: project provisioning, then an official checksummed
  release under `~/dev/` or `~/.local/`, then `uv`/`cargo`/`npm`/Homebrew, then `podman`. Only if
  none works, give the user the exact `sudo` command. Never substitute a different toolchain.
- Browser automation uses WebLua (`weblua` skill), headless, never a personal profile.
- Every windowed product has a hidden-window run mode for tests and maintainer runs: the window is
  created unmapped on the user's own session, presents without vsync, and errors are logged, never
  shown as dialogs. Tools use that mode; no Xvfb, offscreen video drivers or stripped
  `DISPLAY`/`WAYLAND_DISPLAY` inside a tool. A headless CI job wraps the whole job, not the tool.

## Repository and worktree

- One branch, `main`; commit directly. A verified fix is standing authorization to commit and push.
  Commit messages are one line, `type(scope): subject`, plus attribution trailers.
- Every maintained repo has a GitHub `origin`; run the `go-public` audit before making one public.
- Nothing machine-specific in tracked files (no home paths); game assets never enter git.
- Third-party changes are commits in a maintained fork pinned by revision; no `.patch` files.
- Builds go under gitignored `build/`, run artifacts under gitignored `scratch/<activity>/`, never
  `/tmp`. Clean with `tools/scratch_gc.py` or `tools/cleanup-files`, never raw `rm` of broad paths.
  Large CMake builds use Ninja; an unchanged rebuild compiles nothing.
- Account for every change in the tree before ending: land it, continue it, or remove it. Do not
  revert another agent's work. Subagents never stage, commit or push; the operator reviews and lands.
- Kill by PID, never `pkill` a shared name; put this in every brief that launches an app.
