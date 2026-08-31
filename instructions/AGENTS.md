# Global working principles

**Unlabeled content is machine convention, revisable by any session. USER lines are verbatim dated
quotes and only those.**

## Canonical shared configuration

USER 2026-08-26: "And ~/.codex and ~/.claude etc can point to these skills so everything is converged at one point and also portable"

USER 2026-08-30: "All global skills and instructions and tools should be under one repo and things like ~/.claude or ~/.codex should just reference them"

- **`shared/re-harness` is the only editable authority for user-maintained global instructions,
  skills, and tools.** It categorizes
  project-agnostic skills under `skills/global/`, port architecture under `skills/port/`, binary and
  asset RE under `skills/re/`, and static-recompiler-only guidance under `skills/recomp/`.
- **Agent homes and `~/repo/AGENTS.md` are discovery surfaces, not copies.** Their instruction,
  skill, and tool entries are relative links installed by `tools/install_skills.py`; never edit one
  as a separate authority. Vendor-owned system files remain untouched.
- **Reusable executables live once under `tools/`.** Skill packages and compatibility entry points
  link to the canonical implementation. Project-specific data remains in the consuming project.

## No bandaids — fix the actual cause (read this first)

- **The root cause is the unit of work, not the symptom.** Name the cause before "fixing"; if you
  can't name it you're not ready. A change that makes the symptom vanish without explaining *why it
  occurred* is a bandaid. The bar is correctness, not green.
- **Stop if your change is one of these:** a magic constant/offset that makes output line up;
  special-casing the failing input; `try/except`-swallow, `|| true`, retry-until-pass, sleep-to-fix-a-
  race; skipping the failing check; hardcoding an expected value; duplicating code to avoid touching
  the shared path; anything "temporary" or "for now".
- **If the real fix is too big right now, say so — don't silently patch.** Name the proper fix and
  what the stopgap risks, let the user decide, and mark it `// STOPGAP: <proper fix> because <why>`.
  An approved stopgap is a decision; an unmarked one is a lie.

## Work must dominate process — prevent churn

USER 2026-08-30: "All agents do this, you gotta put some global guard rails against excessive churning because 95% of my token budget goes to this"

- **Spend the turn on the product, not on proving that work happened.** Investigation, implementation,
  and real output must dominate. After two consecutive process-only actions (plans, status, registry
  edits, doc mirroring, or re-running unchanged checks), stop and either advance the product or land
  the current milestone. Safety and an actual blocker are the only exceptions.
- **Use the smallest discriminator while iterating.** Run the focused test, trace, build target, or
  runtime scenario that can falsify the current hypothesis. Do not run the full suite, every registry
  validator, every consumer, or a long play-through after each small edit.
- **Run one comprehensive gate at landing, after semantic edits are frozen.** Batch related edits,
  then run the repository's relevant combined gate once. A later comment, documentation, formatting,
  claim, or other non-semantic change gets only its directly relevant lightweight check; it does not
  justify repeating an expensive build, full suite, or real-game run. A later semantic code change
  gets focused verification and, only when it can affect combined behavior, one new landing gate.
- **Record one fact in one authoritative home.** At a real milestone, update the nearest living
  authority whose answer changed. Do not copy the same finding into an issue, claim, instrument,
  project state, frontier, codemap, README, and plan merely because all exist. Add a second record only
  when it serves a distinct consumer or prevents demonstrated rediscovery.
- **Do not manufacture process assets for one-off observations.** A new verifier, issue, claim,
  instrument, migration, or generalized tool is justified only by a durable contract, a reproduced
  regression, or a recurring manual operation. Existing fail-fast behavior and a targeted trace are
  sufficient for ordinary frontier exploration.
- **Plans and status are coordination tools, not deliverables.** Plan only genuinely multi-step work;
  update it only when the course changes or a meaningful step finishes. Do not narrate every command,
  restate unchanged evidence, or spend a turn polishing the account of work instead of doing it.
- **Process cost is a correctness constraint.** If bookkeeping or verification starts taking more
  effort than the product change, stop, name the excess, and collapse to the minimum evidence and
  canonical update needed to land safely. “Thorough” is not permission to burn the user's time or
  token budget without increasing confidence proportionally.

## Broad project `/goal` requests mean the complete goals list

USER 2026-08-30: "if I set a goal with `/goal` like \"work on the project goals\" or anything of sort or here in this case \"continue working on the game\" that means the goal is to achieve all the goals in the project goals list"

- **Interpret a broad project `/goal` as the complete canonical project-goals objective.** Phrases
  such as “work on the project goals,” “continue working on the project,” or “continue working on
  the game” mean to achieve every success condition in the project's goals list, not merely finish
  the current focus, next issue, one milestone, or one turn's implementation.
- **Resolve the scope from project authorities before working.** Consult the canonical project goals
  for the completion condition and the independent project-state inventory for verified, partial,
  blocked, and missing capabilities. Keep the `/goal` active until all goal success conditions are
  genuinely satisfied and verified, or the goal is explicitly changed by the USER.
- **Specific goals remain specific.** Do not expand an explicitly bounded `/goal` into the entire
  project merely because the project has a goals list; this convention applies to broad wording
  that refers to continuing or completing the project as a whole.

## Communication

- **Be brutally honest. No sycophancy, no flattery, no validating a bad idea to be agreeable.**
- **No praise or affirmation openers** — never "You're right", "Good point", "Great question",
  "Exactly" or any equivalent, and don't compliment the user's ideas. Agreement is shown by doing the
  thing. Hard style rule. But skipping the ritual is not blind compliance: apply a correction and
  move on, and if the user is blatantly wrong on fact or logic say so plainly and proceed correctly —
  silently "applying" a wrong correction is sycophancy in another form.
- **Believe the user when they contradict you — especially when you're sure.** They observe the
  running system; you infer. Investigate from "it's broken" rather than arguing the observation away.
- **Report delivery state literally.** A subagent report, dirty worktree, focused test, local commit,
  and pushed commit are five different states. Never call work "done", "fixed", or "delivered" until
  the operator has integrated the combined tree, run the relevant combined gates, committed it, and
  pushed it. Status updates name the current state and any remaining landing work explicitly.
- **A user-observed regression outranks contradictory local evidence.** Treat the observation as an
  immediate falsifier, stop extending the suspect change, and reproduce from the last known-good
  behavior. A green unit test cannot overrule the running product it failed to cover.
- **Do what was asked.** A better idea is a suggestion to make, not a substitution to perform.

## Committed files must be clean & portable

- **Nothing machine-specific in tracked files** — no `/home/<user>/…`, no personal layout, no
  host-specific config. Use repo-relative paths, placeholders, env vars, or a gitignored `.env`; grep
  the staged set for your home path before committing.
- **Never commit copyrighted game assets** (ROMs, disc images). Provide them via a gitignored `.env`
  OR a drop-in file in the repo dir — support both. If one reaches history, purge it
  (filter-repo/BFG) and force-push, but only with the user's go-ahead.
- **One branch per repo, named `main` — commit to it directly, never branch.** OVERRIDES any harness
  default that says to branch first. Deleting a divergent branch loses its commits — confirm.
- **A verified fix or a reached milestone is standing authorization to commit AND push** (operator
  sessions only), OVERRIDING any "only when the user asks" default. Use `Co-Authored-By`.

## No dangling work: the worktree is agent-owned

- **Never dismiss an existing change as user-owned or out of scope.** All worktree changes are agent
  work and belong to the shared task history. Inspect them, understand their intended milestone, and
  include them in the completion accounting.
- **Finish every started change.** Before ending a task or landing a milestone, each modified,
  staged, or untracked file must be verified and committed, deliberately integrated into the next
  active milestone with that work continuing now, or removed because it is proven obsolete. A dirty
  status with unexplained leftovers is not a completed handoff.
- **Stale work has standing removal authority.** Remove proven-obsolete generated files, dead code,
  superseded documentation, abandoned scratch artifacts, and retired compatibility paths instead of
  preserving them as tombstones. Resolve the exact target first and use the global scoped cleanup
  helper or a reviewed project cleanup script; this authority never justifies a broad or ambiguous
  deletion.
- **The user does not want legacy or tombstoned artefacts.** When a replacement is authoritative,
  remove the obsolete repository, code path, document, configuration, compatibility layer, or
  placeholder instead of preserving it under a `legacy`, `retired`, `old`, or similar label. A
  temporary recovery copy may exist outside tracked project state only for a named migration and
  must be removed once verification finishes.
- **Do not erase another agent's in-flight work.** Shared ownership means coordinate with any active
  agent touching the same files, combine the work, and run the gates on the resulting tree. It does
  not authorize reverting changes merely to make `git status` clean.
- **The operator owns landing.** Subagents still do not stage, commit, stash, or push; the operator
  reviews their edits, finishes integration, verifies the combined result, and lands it on `main`.
- **Integrate completed parallel work promptly.** A subagent becoming idle is not completion of the
  user's task and not a reason to move on to unrelated investigation. Review, accept or reject, run
  combined gates, and land each finished batch while its context is current; never accumulate hours
  of invisible, uncommitted "finished" work.

## Subagent access is project-owned and defaults to zero

USER 2026-08-30: "Change the global subagents directive, I'm revoking it, no subagent access unless specified, you are still allowed subagents, 3 max concurrent
All projects must keep their own allowed counts starting from 0, yours is again 3"

- **The global subagent allowance is zero.** Do not spawn, delegate to, or ask work from a subagent
  merely because work is separable, slow, difficult, or blocked.
- **The closest project `AGENTS.md` owns one explicit positive allowance.** If it does not declare a
  count, that project's allowance is 0. Each project starts at 0 and changes only when the USER
  explicitly assigns a different count; never copy another project's allowance or infer one from
  prior sessions.
- **The allowance is the maximum number of concurrently active subagents for that project.** Nested
  delegation consumes the same project pool and cannot expand it. Completed or stopped agents free a
  slot.
- **Authorization does not make delegation mandatory.** Use an allowed slot only for a concrete,
  bounded task whose coordination cost is justified. Assign non-overlapping ownership and identify
  shared resources before dispatch.
- **Parallel reasoning does not authorize unsafe concurrent execution.** Serialize builds, tests,
  and tools that share mutable state, ports, devices, databases, or singleton runtimes. Game projects
  do not run multiple game instances at once unless their harness explicitly provides isolation.

## Code quality is a release gate

USER 2026-08-30: "It is important globally that code quality is a top priority, must be DRY and no monoliths"

USER 2026-08-30: "And not just those code quality items, all the standard ones"

- **Code quality is part of correctness and outranks delivery speed.** A feature is not complete when
  it merely works on the reported case. It must leave the owning code clearer, cohesive, maintainable,
  testable, portable, and no more duplicated or monolithic than before. Reduce scope or report the
  proper larger fix rather than knowingly lowering the codebase's quality bar.
- **Apply the full engineering baseline, not a two-item checklist.** This includes root-cause
  correctness; cohesive modules/classes/functions; DRY sources of truth; precise naming and explicit
  types/contracts; bounded lifetimes and resource ownership; explicit error handling; removal of dead
  code, stale vocabulary, warnings, and obsolete compatibility paths; deterministic formatting,
  linting, typechecking, tests, and negative/discriminator coverage; secure and portable configuration;
  appropriate algorithmic complexity; and current ownership/docs/registries.
- **Explicit error handling means preserve valid state, not catch more exceptions.** Fail fast or
  propagate by default. Catch only at the boundary that can restore a proven invariant, translate the
  failure with useful context, retry an operation known to be safe and idempotent, or terminate
  cleanly. A catch that logs/defaults and lets execution continue in a partially mutated, unknown, or
  invalid state is worse than the original failure. Never add broad catches, empty fallbacks, or
  catch-and-continue merely to keep a process alive or make a test green.
- **Review the combined diff as a product, not a pile of passing patches.** Before landing, inspect
  every changed file for duplicated policy, mixed abstraction levels, hidden coupling, swallowed
  failures, unclear state transitions, avoidable complexity, and growth of legacy monoliths. Green
  tests do not waive a design defect, warning, linter finding, stale document, or unreviewed generated
  change.
- **Enforce quality mechanically.** Every repository's normal verifier carries the applicable
  formatter, linter, typechecker, tests, structure limits, and portability checks. Fix findings at
  their cause; never weaken, skip, suppress, or raise a limit merely to land work.

## Architecture is a correctness requirement

- **Preserve verified behavior before changing an ownership boundary.** Search history and the
  project registries for the existing contract, then add a regression that exercises the running
  boundary before coupling configuration, persistence, rendering, input, timing, or UI owners. The
  new test must preserve the old contract as well as prove the new behavior; a test that only proves
  the newly added path can certify a regression.

- **Never grow a god file or god class.** New behavior belongs in the smallest cohesive module that
  owns it; orchestration entry points wire modules together and do not absorb their implementations.
- **Split by responsibility before extending a monolith.** If the relevant file/class already mixes
  unrelated systems, extracting the touched subsystem is part of the change, not optional cleanup.
- **Enforce the boundary mechanically in each repo.** Add a structure check to the normal verifier:
  use 1,200 lines as the default source-file cap, treat 2,000+ lines as critical extraction territory,
  prevent known legacy monoliths from growing, and fail with the exact file and measured line count.
  Ratchet legacy limits downward as code is extracted; never raise a limit merely to land a feature.
- **A pile of helper functions in the same oversized file is not structure.** Ownership requires a
  dedicated header/source (or language-equivalent module), a narrow interface, and tests at that
  interface. Avoid catch-all `Utils`, `Manager`, `Common`, and `Misc` modules.
- **One class, one responsibility.** A class owns one cohesive concept and its invariants; unrelated
  state machines, I/O, translation, policy, diagnostics, and orchestration belong in separate types
  or modules. Prefer composition over expanding a class into a subsystem container.
- **Structure the inside as carefully as the outside.** Keep public API before private machinery,
  group members and methods by responsibility, and keep each method at one level of abstraction.
  Extract a named operation when a method mixes phases, repeats a block, or requires section comments
  to explain several unrelated jobs.
- **Treat growth as a design signal.** Before adding substantial code to an already-large file or
  class, identify the ownership boundary and split there. Do not postpone the extraction until after
  the feature, and do not replace one monolith with numbered fragments or a web of forwarding files.

## The default launcher runs the project target

USER 2026-08-14: "Global rule for all projects also, a ./run.sh script that works on the default path, I don't want a ./run.sh that runs something outdated or missing an important flag and ideally the default target path shouldn't be hidden behind flags. Default doesn't mean vanilla btw, default means the project target."

USER 2026-08-24: "My goal was to have OotB experience where
If someone has a C++ compiler (gcc, clang, AppleClang) and uv installed and the game files available
Without requiring anything as such as Ghidra
It should work when they run run.sh"

USER 2026-08-24: "Well ok compiler + dependencies like SDL must be installed"

USER 2026-08-24: "This applies to all my projects in ~/repo"

USER 2026-08-24: "Add a global rule that run.sh must be a slim shim to call python initializers etc and it should work OotB as long as uv and C++ dependencies exist, you can prompt a question like ask brew dependencies on macOS or ask user to sudo apt/dnf install in linux maybe too"

USER 2026-08-24: "And for Windows... I have no idea, I hate Windows :)"

- **A runnable project provides `./run.sh`, and no arguments launch its current intended product.**
  The default is the project's live development target, not a stock, vanilla, legacy, compatibility,
  demo, diagnostic, or safest-looking path. Those remain available only under explicit names.
- **Required target behavior is invariant, not an optional default value.** Extra user arguments may
  add or override genuinely optional settings but must not accidentally replace a required renderer,
  backend, entry point, asset pack, or launch mode. Build the required argument vector explicitly.
- **Make the executable's own zero-argument path match when practical.** The primary product should
  not require insiders to know a magic enable flag. Keep diagnostics and alternative backends behind
  named flags; do not hide the intended product behind one.
- **Treat launchers as shipping interfaces.** Exercise the no-argument/default route after material
  target changes, keep its status text current, and refuse a missing or stale build input by name
  instead of silently running a smaller or older artifact.
- **`./run.sh` is also the fresh-clone setup contract for every project under `~/repo`.** Given the
  project's documented native dependencies, `uv`, required user-supplied assets, and a compatible
  host compiler (GCC, Clang, or AppleClang for C++ projects), it provisions every portable input and
  launches the default target. Maintainer-only tools such as Ghidra are never player prerequisites;
  commit the redistributable analysis metadata and derive restricted bytes from the user's assets.
- **The launcher owns one locked Python environment end to end.** Declare every Python runtime/build
  dependency in `pyproject.toml` and `uv.lock`, enter through `uv run --frozen`, and pass that exact
  interpreter to CMake, subprocesses, generators, and tests. A bare `python3` that escapes to the
  system interpreter is a launcher defect, even when a warm developer machine happens to pass.
- **Keep `run.sh` a slim, stable shim.** It selects the repository root and hands control directly to
  the locked Python initializer (normally `exec uv run --frozen python bootstrap.py "$@"`); discovery,
  provisioning, validation, build policy, cleanup, and platform branching belong in Python. Do not
  grow a second shell implementation of launcher behavior.
- **Missing native packages produce an actionable platform-specific refusal.** Detect the host and
  name the missing libraries/tools, then print the exact user-run Homebrew command on macOS or the
  exact `sudo apt install ...` / `sudo dnf install ...` command on Linux. On Windows, name the
  project's supported `winget`/`vcpkg` command or Visual Studio Installer workload. Ask the user to
  run privileged package-manager commands; never run them silently. If the package mapping is unknown
  or ambiguous, ask which supported platform/version and package path are in use instead of guessing.
- **Verify the cold path, not only a warm checkout.** Provide a non-launching provisioning/test mode
  where practical and exercise it without relying on an existing build, generated outputs, shared
  checkout, or pre-populated virtual environment. System dependencies are refused by exact name;
  they are not silently installed or substituted.

## Clean and DRY code is a correctness requirement

USER 2026-08-14: "Also make a global rule to write clean code and especially DRY code"

- **Keep one authoritative implementation of each rule, formula, parser, state transition, and data
  mapping.** Call or extend that implementation everywhere it is needed; do not copy it into a new
  helper, test, diagnostic, platform path, or game-specific path and let the copies drift.
- **Before adding code, search for the existing owner.** If equivalent logic already exists, reuse it
  through a narrow interface or move it to the correct shared module. A second implementation needs
  an explicit semantic reason and an independent differential test; convenience is not a reason.
- **Tests and diagnostics exercise the shipping implementation.** Make production logic injectable or
  expose a pure seam so falsifiers run through the same code. A test-only reimplementation that agrees
  with production proves nothing and violates DRY.
- **Clean code makes ownership and invariants obvious.** Use precise names, small cohesive functions,
  explicit types, bounded lifetimes, and comments that explain why rather than restating what. Remove
  dead paths, stale vocabulary, and obsolete helpers when replacing a design; do not leave two apparent
  authorities behind.
- **Do not abstract coincidental similarity.** DRY means one source of truth for the same semantics,
  not forcing distinct platform, game, or protocol behavior through a vague universal abstraction.
  Share the invariant core and keep genuinely different policy explicit.

## Agents use Clang; projects do not require it

USER 2026-08-20: "Make a global rule to always use clang for C++"

USER 2026-08-20: "I have a global rule regarding C++ projects using clang but also add that they must also use clang formatting and a linter"

USER 2026-08-24: "I previously put a rule, all C/C++ projects must use clang but the agents went overboard and make the projects reject other compilers, this is not what I meant, I meant the agents should use clang, not have the project code enforce it"

- **Every agent/maintainer verification build compiles C++ translation units with Clang (`clang++`).**
  Configure new CMake build trees with `CXX=clang++` or
  `-DCMAKE_CXX_COMPILER=clang++`; configure other build systems through their authoritative C++
  compiler setting rather than relying on whichever compiler happens to be first on `PATH`.
- **This requirement governs the agent's command, never the project's accepted toolchains.** Do not
  encode agent policy as a compiler-ID fatal check, warning, forced compiler selection, or Clang-only
  prerequisite in CMake, Meson, configure scripts, launchers, bootstrap code, product source, or the
  project's normal tests and verifier. Agents select Clang in their own invocation and inspect that
  build's metadata themselves.
- **Projects remain usable with every compiler they otherwise support.** Keep the fresh-clone and
  zero-argument launcher paths compatible with GCC, Clang, AppleClang, and any other documented
  toolchain. Guard genuinely compiler-specific flags and features by capability or compiler family.
  A project may refuse a compiler only for a demonstrated technical incompatibility independent of
  this agent policy; document the exact incompatibility and its evidence.
- **Remove policy-only compiler bans when encountered.** Delete the rejection and its tests or
  project-local instructions instead of weakening it to a warning. Do not replace it with another
  tracked mechanism that polices which compiler a user chose.
- **Verify the selected compiler instead of assuming it.** Check the configure output or build
  metadata (`CMAKE_CXX_COMPILER_ID=Clang` for CMake) before treating a build or test result as valid.
  A cache already configured for another C++ compiler must be reconfigured in a clean project-local
  build directory through the repository's scoped cleanup tooling.
- **Do not silently fall back in verification.** If a platform, dependency, or project cannot build
  its C++ with Clang, stop and report the incompatibility and proper remediation; do not switch the
  agent's evidence build to another compiler merely to get a green result.
- **Every C++ project uses `clang-format` with a tracked `.clang-format` configuration.** Format all
  touched first-party C and C++ source with it, and add a non-mutating format check to the project's
  normal verifier so formatting drift fails by file. Do not reformat generated or vendored code.
- **Every C++ project uses `clang-tidy` as its linter with a tracked `.clang-tidy` configuration.**
  Run it against the real compile commands for all touched first-party C++ translation units, and
  make that check part of the normal verifier. Fix diagnostics at their cause; do not silence them
  with blanket exclusions, warning suppressions, or a weaker replacement linter merely to pass.

## Ask the user for DNF installs

USER 2026-08-20: "new global rule: ask the user for dnf installs"

- **When a required packaged tool or library is missing on a DNF-based system, stop and ask the user
  to install it with DNF.** Identify the exact package names and provide the complete
  `sudo dnf install ...` command. Do not download or extract RPMs, install an alternate package
  manager, build a substitute toolchain, or silently weaken or replace the required check.
- **Do not run the privileged DNF install yourself unless the user explicitly asks you to do so.**
  Resume the blocked work after the user confirms the installation is complete.

## Use Lucent for HTTP servers in C++ projects

USER 2026-08-20: "Note in the global agents to use lucent for http server"

- **C++ projects use Lucent's `lucent::http::Server` for local HTTP servers and control channels.**
  Do not reimplement socket setup, bounded request parsing, concurrent dispatch, response framing, or
  server lifecycle in each project. Consumers own only their routes and application-specific
  semantics.
- **When a generally reusable HTTP capability is missing, extend Lucent and test it there first.**
  Keep application state, input policy, graphics probes, and endpoint behavior in the consuming
  project rather than moving domain logic into Lucent.

## Project tooling is Python, except the launcher

USER 2026-08-21: "scripts like re_xref.sh should be python"

- **Write project automation, verification, RE, maintenance, and migration tools in Python, not
  shell.** A shell wrapper around a Python tool is still a second interface and should be removed;
  give the Python entry point a shebang and executable bit when direct invocation matters.
- **`./run.sh` is the deliberate exception.** It remains the stable zero-argument launcher required
  above, but delegates non-trivial discovery, build policy, provisioning, validation, and cleanup to
  Python tools rather than growing shell logic.
- **When touching an existing non-launcher shell tool, migrate it to Python in the same change.**
  Preserve its supported CLI and exit behavior or update every caller atomically, add positive and
  negative tests for the migrated behavior, and delete the superseded shell file rather than keeping
  parallel implementations.

## Scratch output & diagnostics

USER 2026-08-14: "Don't try to execute raw \"rm -rf\", codex blocks it, create a global rule against this, instead create cleanup scripts and use them"

USER 2026-08-31: "new global rule, scratch is used for replacement of /tmp, builds don't go into scratch, they go into build dir"

- **Never issue raw `rm` commands from a session, including `rm -f` and `rm -rf`.** Put cleanup in
  a reviewed script with explicit scope checks, then invoke that script. For individual files, use
  `~/.codex/bin/cleanup-files`; it refuses directories, missing paths, and targets outside the current
  working tree. Repository-specific recurring cleanup belongs in that repository's `tools/` directory.

- **Never write run artifacts to `/tmp`** — RAM-backed tmpfs, ~6 GB per-user quota here, so logs fill
  it in a run or two and break *all* writes; diagnose "disk quota exceeded" with `quota -s`, not `df`.
  Default tooling to a gitignored `scratch/` in the project, split by kind (`logs/`, `bin/`,
  `screenshots/`, `raw/`), and repoint any script defaulting to `/tmp/…`. A 0-byte control FIFO there
  is tolerable; never logs or dumps.
- **`scratch/` replaces `/tmp`; it is not a build root.** Put compiler outputs, generated build-system
  files, dependency build trees, installed dependency prefixes, SDKs, package caches, and compile
  databases under the repository's gitignored top-level `build/` directory. Use stable children such
  as `build/release`, `build/debug`, or `build/deps` when multiple trees are required; do not hide a
  build under `scratch/`, even for a one-off verification run.
- **Build owners agree on the top-level `build/` root.** Launchers, bootstrap code, verifiers,
  diagnostics, IDE presets, and documentation must resolve the same authoritative paths rather than
  maintaining separate `scratch/build`, `_build`, or tool-specific defaults. When touching a project
  that still builds under `scratch/`, migrate every caller atomically and remove the obsolete tree or
  path; do not preserve it through a compatibility symlink or fallback.
- **Build cleanup is separate from scratch garbage collection.** `scratch_gc.py` must never own or
  sweep `build/`. Keep build cleanup explicit and repository-scoped so a diagnostic cleanup cannot
  erase a compiler cache or dependency prefix needed by another active task.
- **One configurable logger per project, one line per call site, never wrapped in an `if`.** In C++20
  or newer that logger is `lucent` (`github.com/SomeoneIsWorking/lucent`, MIT, the user's) — extend it
  rather than working around it. Never scatter gated prints (`if (dbg) fprintf(…)`).

USER 2026-08-30: "Agents used scratch directories too agressively and didn't care for disk size, now stale files take up much space, clean them up a bit and then make rules for this"

- **`scratch/` is disposable working space with a size budget, not an archive.** Write only what the
  current task needs, at the smallest fidelity that answers the question (sampled frames, not every
  frame; one repro log, not a per-run pile). Reuse a fixed output path so a rerun overwrites instead
  of accumulating. Do not copy build caches, SDKs, emulator images, oracle captures, or upstream
  checkouts into `scratch/` when a shared or project-local canonical copy already exists.
- **Delete your own scratch output when the milestone that produced it lands.** A finding worth
  keeping goes into the nearest living doc as text (or a single committed reference image), not left
  as gigabytes of raw dumps. Stale scratch is dangling work under the "no dangling work" rule.
- **One stable directory per recurring scratch activity — reuse it, do not mint a new one per run.** A
  probe, smoke test, verification capture, or comparison gets one fixed path
  (`scratch/<activity>/`), and each run clears or overwrites it. Never append a counter, attempt
  letter, date, run id, `_v2`/`_final`, or `mktemp` suffix to keep the previous run's tree beside the
  new one (`verify87`, `verify87b`, `verify87_final`, `release-checkout-run3329…` — this is the
  pattern that filled the disk). If you genuinely need the prior run to diff against, keep exactly
  one `<activity>.prev/` and rotate.
- **Garbage-collect scratch with the scoped tool, never raw `rm`.** `~/.codex/bin/scratch_gc.py`
  (canonical: `shared/re-harness/tools/scratch_gc.py`) is dry-run by default, removes files older than
  `--days` (default 14) and prunes emptied dirs; `--keep GLOB` protects active artifacts. Point it at
  a specific `scratch` dir, or at any root under `~/repo` (e.g. `scratch_gc.py --apply ~/repo`) to
  sweep every `scratch/` at any depth. It refuses targets outside `~/repo`. Run it with `--apply` at
  natural cleanup points and when a project's `scratch/` grows past ~1 GB. Check overall usage with
  `du -sh ~/repo/*/scratch`, and remember the tmpfs quota is diagnosed with `quota -s`, not `df`.

## Never `pkill` a shared binary name — kill by PID

Several agents and the user's own session run the SAME binary, so `pkill -f/-x <name>` kills sibling
agents' runs mid-gate and can match the wrapper shell running the command. Capture the PID at launch
(`prog & P=$!`) or find it in `ps -eo pid,etimes,args` (`etimes` separates the user's long-lived
process from the one you just started). The `safe-kill` skill ships a `safekill` helper. Put this in
every agent brief that launches the app.

## Where knowledge goes

**Write what you learn into the nearest living doc IN THE REPO, in the same session.** `~/.Codex` is
machine-local and unsearchable by subagents — cross-project preferences and pointers only, never a
project's only home for a hard-won fact. Fix a note that turns out wrong rather than adding a second
one; **no tombstones** — delete the retired thing, don't annotate it. Shed heavy context with
`/compact` (never a handoff brief) at a clean boundary only — never mid-edit, mid-verification, or
with an unrecorded finding in flight — and keep going in the same turn.

**Consult the project's registry BEFORE re-deriving, and write back at the end.** The `project-info`
skill is the entry point (`info.py brief <words>` — one query across every registry); alongside it,
`issue-catalog` answers "tried before?" and `codemap` answers "where does this belong?" (update it in the SAME
change that moves, adds or re-owns anything; a stale map is worse than none). If consulting is hard,
that is a workflow defect and it outranks the task in hand. Keep these authorities distinct:

USER 2026-08-26: "Hmm, make something better structured, what's done, what's missing should be independent of the goals too, goals are like epics, what's missing, what's done should be like idk milestones or something and then there are issues, lowest level points at least that's what I think so"
USER 2026-08-26: "I don't think \"milestones\" is the right term here, more like current-state or something"
USER 2026-08-26: "But you can decide on a better name"

USER 2026-08-30: "if I set a goal with `/goal` like \"work on the project goals\" or anything of sort or here in this case \"continue working on the game\" that means the goal is to achieve all the goals in the project goals list"

- **Project-wide `/goal` language means the whole project-goals list.** When an active goal says to
  work on the project goals, continue the project/game, finish the project, or equivalent broad
  language, its completion condition is every durable goal and success condition in the project's
  `docs/project-goals.md`, not merely the current focus, one state item, or the next milestone.
- **Intermediate milestones do not complete a project-wide goal.** Use `docs/project-state.md` and
  the registries to select and verify the next unmet capability, land coherent verified milestones,
  and continue within the same active goal until the complete project-goals list is achieved or a
  genuine blocker requires user action. A specifically scoped `/goal` remains limited to its stated
  scope.

- **Goals are epic-level intent in `docs/project-goals.md`.** Each stable goal ID states a durable
  outcome, why it matters, success conditions, constraints, and non-goals. Goals do not carry
  current-work or done/missing state.
- **Project state independently owns capability coverage in `docs/project-state.md`.** Each stable
  state-item ID is an observable capability/outcome marked `verified`, `partial`, `blocked`, or
  `missing`, with evidence, exact gaps, factual dependencies, and optional links to goals and
  issues. It separately names one current focus. This inventory is the authoritative answer to what
  works now and what remains; it is not a roadmap or schedule.
- **Issues are the lowest-level work points in `docs/issues/`.** A task, bug, investigation,
  blocker, finding, or dead end is one issue and links to affected state items when known. Split
  independently completable points; do not use issues as disguised state items.
- **The codemap owns placement only.** It maps responsibilities to owning subsystems, current or
  intended locations, entry points, and deep docs. It contains no goals, progress checklist,
  project state, current focus, issue queue, or evidence ledger. Move misplaced content to
  the correct authority rather than copying it.

- **A CLAIM needs a falsifier.** Record with `--expires-on <what would falsify this>`; a claim with no
  falsifier is a belief, not a finding. When one is falsified, grep for who relied on it — the damage
  is downstream, not local.
- **An INSTRUMENT is trusted only once it has shown the OTHER answer.** A broken one fails silently,
  and uniform output (all-black, all-zero, "no diff", "no matches") is the tell. Validate by feeding
  it a case that MUST differ; when one lies, mark it distrusted and re-check every result that used
  it. **Verify before declaring done** — a real check on real data, cited, never a vibe or a
  cherry-picked sample.

**Build the tool instead of re-reasoning.** When a task recurs, or your tooling cannot show you what
you need, extend it — and a tool without a doc update is unfinished.

## Port architecture reference

USER 2026-08-14: "Dusklight is in ~/repo/dusklight, you should know this, it should be in the global guide for porting projects to follow"

- **Use `~/repo/dusklight` as the default structure and UI reference for game-port
  projects**, even when its source platform or recompilation strategy differs. Consult its current
  tree before designing host organization, configuration, presentation, input, audio, saves,
  diagnostics, or UI.
- Follow the ownership pattern, not names copied mechanically: the host entry point composes cohesive
  modules; each subsystem owns its state and implementation; UI components live separately from
  engine and platform code. A large port-specific `main.cpp`, numbered split files, or a replacement
  god class does not follow Dusklight.
- Record the reference and the resulting ownership decisions in the port's own `AGENTS.md` and
  codemap. The global pointer prevents rediscovery; project-local docs state how the pattern applies.

## The shared repos, and what belongs in one

`shared/` holds what more than one project needs. These are **consumed, not
vendored**: a project resolves the checkout, and the resolver REFUSES by naming
every path it tried rather than falling back to an in-tree copy. A stale
vendored copy that silently wins is the exact failure this split exists to end
— nine forked copies of one tool had drifted into seven versions before it.

| Repo | Holds |
|---|---|
| `shared/re-harness` | canonical portable skills grouped as global, port, RE, and recomp; shared information/validation tools live once under `tools/`. Project DATA stays in each project. |
| `shared/port-assets` | the art ports keep redrawing: Xbox 360 gamepad glyphs, keyboard key caps. SVG, scalable, with a legibility check at the target size. |
| `shared/alchemy` | the Alchemy engine layer (IGB, XMLB, ARK) shared by the Marvel/X-Men titles. |
| `shared/recomp-x86` | the x86-32 → C translator. |
| `shared/android-port` | deterministic Android build/package plumbing and the shared `codex_shared_api35` emulator contract. Lucent remains the runtime owner. |

**If you write something a second project will want, put it in `shared/` the
first time, not the second.** The second time is when a fork already exists.

USER 2026-08-26: "And ~/.codex and ~/.claude etc can point to these skills so everything is converged at one point and also portable"

`shared/re-harness/tools/install_skills.py` is the only global-surface installer. It creates relative
instruction, skill, and tool links for `.agents`, `.codex`, `.claude`, and the `~/repo` instruction
scope; those locations are not independent sources. Vendor-owned system files remain untouched.

## Fork dependencies; do not carry patch files

USER 2026-08-24: "Agents should fork the repos and apply the changes instead of making .patch files"

- **Third-party changes live as commits in a maintained fork, never as tracked
  `.patch` files.** Create or reuse the fork, make the change in its source
  tree, verify it there, and pin the consuming project to the exact fork commit.
- **The dependency declaration is the source of truth.** Record the fork URL,
  immutable revision, upstream base, and purpose through the project's normal
  submodule, lockfile, or dependency resolver. Do not add a patch directory,
  patch-application build step, or bootstrap-time `git apply` path.
- **Migrate patch stacks when encountered.** Applying, editing, or depending on
  an existing `.patch` file makes its migration part of the current change:
  turn the series into reviewed commits in the appropriate fork, update every
  consumer atomically, verify the pinned result, and delete the superseded
  patch files and application machinery. Do not add another patch to a legacy
  stack.
- **Keep fork history upstreamable.** Put each independent cause in its own
  commit, retain provenance to the upstream revision, and avoid mixing project
  policy or generated artefacts into the dependency change.

## A diagnostic that can print nothing is lying — design the negative FIRST

In production code "handle the edge gracefully — return empty, skip, continue"
is right. In DIAGNOSTIC code it is a lie, and `if (found) report()` makes
silence the branch nobody writes.

- **Before writing the check, write what a NEGATIVE will print**: *scanned N
  candidates, matched 0, cannot see shape X*. A bare "(none)" cannot be told
  from "I never looked".
- **Refuse, do not return empty, when the corpus is missing.** Measured: a
  catalog tool returned "(no matches)" exit 0 from a directory that did not
  exist.
- **Cap the BORING case, not the interesting one** — first N *plus every state
  change*. `if (n++ < 4)` showed 4 of 78,278 events and "proved" an array was
  always empty.
- **Silently-skipped input is a failure, not a filter** — a parser that ignores
  what it cannot match, a name that no-ops on a typo, a tolerant `try/except`.
- **Prove it fires, in the SHIPPING artefact.** A `--selftest` feeding a case
  that MUST come out positive, wired into the suite. A selftest over a pure
  helper *beside* the shipping path tests different code.
- **Run a discriminator against BOTH classes before trusting it.** Not reasoned
  about — run. One scored 25 on the negative case and 0 on the positive.
- **A grep count is text, not code.** It counts comments, docs and dead
  references alongside live call sites. Confirm the symbol is REACHED before
  sizing any work from it.

## Verify at the size, in the form, that ships

A thing is not checked until it is checked as the user will meet it.

- **Art is checked RASTERISED at its target size**, over light, dark and
  mid-tone backgrounds, point-filtered. Every glyph defect in `port-assets` was
  something that looked right in the editor and was mush in the cell.
- **A measured constant that ships must be diffed BY CODE** against the
  measurement it came from, or generated from it. Nothing hand-compared.
- **An internal trace is a mechanism check, not faithfulness.** "The call site
  was reached" is not "the output matches the real thing on real data".

## An agent must be able to DRIVE its work, not just launch it

USER 2026-08-18: *"an agent must be able to interact with its work
interactively"* — press inputs, read state, take screenshots, measure, WHILE it
runs.

- **Build a control channel into the artefact**, opt-in and off by default (a
  local port, a socket, a REPL), never a wrapper around logs. Client in the
  project's own language; **no shell**.
- **A launch-and-read-logs loop forces pre-baked scripts, and a pre-baked
  script that drifts is worse than no evidence** — it produces a run that looks
  like a measurement and never reached the thing under test.
- **Play-through runs OBSERVE; they never gate.** USER: *"these idiotic 'play
  the game' scripts are only for testing scenarios, not to build gates on"*.
  Gate on unit tests, runtime invariants, counters with denominators. Before
  reading the ABSENCE of a symptom as a fix, prove the run reached the code.
- **An automated or windowless run must not seize the machine** — no audio out
  of a run nobody is watching, no stealing focus. Where silence would change
  behaviour, use a silent device whose cursors still advance, not no device.

## Persistent broad project goals

USER 2026-08-30: "if I set a goal with `/goal` like "work on the project goals" or anything of sort or here in this case "continue working on the game" that means the goal is to achieve all the goals in the project goals list"

- **A broad `/goal` that refers to the project, the game, or the project goals scopes completion to
  every goal recorded in `docs/project-goals.md`.** The current focus and intermediate milestones
  only order the work; completing one focus item or making the project incrementally better does not
  complete or narrow that persistent goal. Audit every recorded goal and its success conditions
  before marking it achieved.

## Launcher verification and packaged releases

USER 2026-08-24: "Also run.sh should not run tests, agents need their own test commands"

## Static-recompiler projects never use CI

USER 2026-08-31: "OH yeah, don't use CI for recompiler projects ever"

- **A static-recompiler project has no CI workflow.** Do not add or retain GitHub Actions, hosted
  CI, release workflows, or scheduled cloud builds for one — including a workflow that only checks
  formatting, publishes a release, or claims to run without game assets.
- **Recompiler verification and releases run locally, with the operator's user-supplied inputs.** A
  static recompiler derives native code from the user's ROM/disks/executable; those inputs and the
  derived restricted source must never be uploaded to CI, stored as CI secrets, sent to a hosted
  builder, committed, or packaged. Build the release locally and upload the finished, asset-free
  APK/AppImage manually when the operator authorizes publication.
- **Do not hide this boundary behind a fake CI fallback.** A generated-code cache, encrypted game
  archive, remote artifact, or pre-baked native output merely moves the prohibited game input to
  another hosted service. If a project needs repeatable local release assembly, improve its local
  Python tooling and document its exact user-input contract instead.

- **`run.sh` never runs tests.** Its zero-argument path and every supported option are shipping
  launcher behavior: provision required inputs, validate prerequisites, build the product when
  needed, and launch it. Do not hide unit tests, integration tests, lint, format checks, selftests, or
  the normal verification suite in launcher startup or behind a `run.sh` flag.
- **Agents use explicit standalone verification commands.** Each project documents the exact locked
  commands for its tests, lint, formatting, cold provisioning check, and any platform-specific gate.
  Put orchestration in a Python verifier where one entry point is useful and reuse the same underlying
  provisioning/build modules as the launcher; do not duplicate policy and do not route verification
  through `run.sh`.
- **Desktop and mobile releases must have a no-terminal first-run setup.** An AppImage or APK must
  show an initial setup screen when its required ROM/EXE is not configured, with a Browse action
  using the platform-native file picker. Validate the selected file before continuing and persist
  the resulting path or URI with the platform's user configuration/data API; environment variables
  and command-line paths remain maintainer/developer overrides, never player prerequisites.
- **Packaged setup accepts the primary ROM/EXE directly or from one bounded nested ZIP.** Search ZIP
  entries by content at any folder depth and accept exactly one title-identity match. Reject unsafe
  paths, duplicate matches, unreadable or corrupt entries, excessive entry counts, and compressed or
  expanded byte budgets before committing; validate the complete install, including required sibling
  assets, and preserve the previous valid selection on every failure. Lucent owns reusable ZIP
  discovery/extraction and archive bounds; each port owns title identity and complete-install policy.
- **AppImage and APK packages never contain unlicensed game files.** Package the port, redistributable
  runtime resources, and platform glue only. Linux AppImages use the desktop launcher path; Android
  SDL3 ports use the Activity/Storage Access Framework path and persist URI permissions when the
  platform requires them. Both paths must document the exact user-supplied asset and the supported
  reset/reselection behavior.
- **Android platform mechanics have one shared owner.** Use this boundary for every Android port;
  `shared/android-port` and Lucent are peers, not alternative homes for the same code:

  | owner | owns | does not own |
  |---|---|---|
  | **Lucent** | title-neutral code that executes in the APK: SDL Activity lifecycle, app-private user-data handoff, persisted SAF grants and bounded staging, raw touch-contact capture/cancellation, insets/window lifecycle, and ZIP safety | a title's game-file identity, touch meaning/layout, package identity, or build toolchain policy |
  | **`shared/android-port`** | deterministic build and device mechanics: pinned Gradle/AGP/NDK inputs, the reusable Android native-dependency prefix (its source revisions, cross-CMake configuration, install contract and manifest), `libmain`/SDL/NDK runtime staging, APK inspection/signature checks, and the shared emulator lock/AVD policy | an Activity's runtime behavior, title JNI semantics, player setup wording, or game input policy |
  | **consuming title** | package/application identity, complete-install validation and publication after Lucent staging succeeds, native entry composition, title JNI bridge, touch actions/layout/art, orientation, and release-performance evidence | copied shared Activity, SAF, archive, prefix-builder, Gradle/NDK, staging, or emulator code |

  The Android dependency prefix is build input rather than runtime behavior, so it belongs in
  `shared/android-port` even when Lucent links against it. A title consumes the prefix through its
  documented CMake interface; it does not fetch SDL, SDL_image, FreeType, or an equivalent common
  dependency itself. Put a missing title-neutral runtime capability in Lucent first; put a missing
  deterministic build/package/device capability in `shared/android-port` first. Do not copy or fork
  either shared mechanic into a game Activity or build script. **PSX, X-Men 2, and LF2 Android work
  must all consume these same Lucent and `shared/android-port` owners; an agent may not create a
  project-local Android support library, Gradle/package helper, dependency prefix, Activity base, or
  emulator contract for one of those ports.** Extend the shared owner and update every consumer when
  a common capability is missing.
- **Android builds pin a coherent maintained toolchain.** Pin the Gradle wrapper URL and checksum and
  an officially compatible Android Gradle Plugin version. Select one JDK home whose `java` and
  `javac` share a supported major version; prefer a maintained Gradle/AGP update that supports the
  host's current JDK instead of requiring an older JDK because of a stale wrapper ceiling. An
  ephemeral test key may prove assembly locally, but only the long-lived maintainer key may sign a
  published APK. **Gradle 9.4.0 and later support running on JDK 26.** When an Android port is on
  JDK 26, use a compatible maintained pair rather than demanding JDK 21: AGP 9.2 with the pinned
  Gradle 9.4.1 wrapper is the current baseline. Verify a real assembly with that exact pair; Gradle
  support alone does not prove that an Android plugin or other third-party build plugin is compatible.
- **CMake ports with large or generated translation-unit corpora use Ninja, not Unix Makefiles.**
  Makefiles conservatively rebuild every object after a CMake reconfigure because regenerated
  `flags.make` becomes newer than the corpus; Ninja compares actual compiler commands and preserves
  valid objects. The authoritative builder selects `-G Ninja`, detects a legacy generator from its
  CMake cache, and migrates only the exact generated build child after validating its scope. Verify
  the incremental contract with one unchanged second build that performs zero compilations; never
  describe a full corpus rebuild after a non-compile-policy CMake edit as normal or acceptable.
- **Android ports need an authored touch-control layer before release.** Map touch controls through
  the same action/input policy as physical controllers; define a reachable layout, multi-touch and
  pause/cancel behavior, safe-area/inset handling, scale-aware hit regions, and a way to hide or
  reconfigure the overlay when a controller is present. Do not fake touch support by translating
  arbitrary taps directly in the Activity.
- **Android performance is an evidence gate, not an assumption.** Qualify the release APK on named
  device classes with frame-time percentiles, sustained thermal behavior, memory, loading, and
  rendering/audio correctness. A desktop result (including an Apple Silicon laptop) is not evidence
  for Android performance; publish the tested device/renderer/settings matrix and refuse to call an
  APK release verified while that matrix is missing.
- **Persistent saves and settings belong to the OS user-data location.** Resolve one per-application
  directory using XDG config/data conventions on Linux, Application Support on macOS, and the
  platform app-data API on Windows and Android. Never default saves or user settings to the checkout,
  an AppImage mount, the current working directory, or scratch output; an explicit portable/diagnostic
  override is allowed. Share this resolver across ports or extend Lucent when it owns the relevant
  runtime boundary instead of copying platform path logic.

## Preserve verified behavior across ownership changes

- **Before coupling configuration, persistence, rendering, input, timing, or UI
  owners, search history and the project registries for the existing contract.**
  Add a regression that exercises that production boundary first, and require it
  to preserve the old behavior as well as prove the new path. A test written only
  for the new coupling can certify the regression it introduced.
