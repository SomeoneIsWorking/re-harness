---
id: 0001
title: Hot reload for C++ projects
status: planned (not started)
created: 2026-11-12
---

# Hot reload for C++ projects

## Request

The user, 2026-11-12, about C++ builds costing too much disk, RAM and CPU: "I even thought about
like 'what if I make a C++ interpreter' to cut down on build resources". When offered hot reload
instead, the user asked "is this feasible?" and then said "Write a plan for this but don't start
it yet", "Actually make the plan for all C++ projects in re-harness maybe".

Start after the build-footprint work lands in psxport and openSU, because both change the same
build modules. That work is lighter debug info, lld under Clang, a shared dependency prefix and
one build tree per purpose.

## Goal

In a maintainer build of any C++ project, an edit to the project's own logic rebuilds one small
shared library, and the running product picks it up at its next safe point. The product is not
relinked or restarted, and the user stays on the same screen. An edit that cannot be reloaded
safely falls back to snapshot, restart and restore, which still lands on the same screen.

Shipped builds stay statically linked, so players see no difference.

## Ownership

- **Lucent owns the mechanism**, because it is title-neutral C++ (`lucent::reload`):
  - loading a new library version;
  - keeping old versions mapped;
  - watching the file and taking a `reload` command;
  - the layout guard, and reporting each reload and refusal.
- **Each framework owns its swap.** It decides its safe point, what a reload replaces and what it
  invalidates: psxport, x86port, snesport, nesport, amigaport, gcnport, and openSU's runtime.
- **The build split is shared CMake**, in Lucent, consumed by every project:
  - a maintainer configure builds the reloadable part as a `MODULE` library and the rest as the
    executable;
  - a player or release configure links it statically from the same sources.
- **This repo owns the rule.** Once the mechanism has shipped in two projects, a skill
  (`hot-reload`) records how a project adopts it.

## Design

- **One entry point per library.** The library exports one versioned function that returns its
  registrations: overrides, behaviour handlers, menus, settings. Nothing else crosses the boundary.
- **Safe point.** Each framework names the point where no reloadable code is on any thread's
  stack, for example between logic frames with the dispatcher idle. The swap runs only there.
- **Old versions are never unloaded.** A stale function pointer, vtable or static then cannot
  fault. Each reload costs a few MB of mappings for the rest of the session.
- **State stays outside the library.**
  - Host-side state the reloadable code needs lives in framework-owned storage, handed back by
    handle, or is rebuilt from the authoritative state on reload.
  - Each adopting project audits its owners for this.
  - Ports are the easy case: the game's state is guest state, owned by the runtime.
- **Layout guard.**
  - The library records a hash of the framework headers it was compiled against. The executable
    checks it before swapping.
  - A mismatch means a shared struct or class changed, and takes the fallback path.
  - No silent swap across an ABI change.
- **Fallback.**
  - The framework's own snapshot (machine state in a port, session state elsewhere) is saved, the
    process restarts on the new build and restores it.
  - A project without a snapshot shows a named refusal instead of reloading.
- **Invalidation.** A port drops every translated block and cached dispatch decision that refers
  to the old library, through its existing invalidation owner.
- **Hosts.**
  - Linux and macOS use `dlopen`.
  - Windows copies the DLL before `LoadLibrary`, because a loaded file is locked.
  - Android and release packages keep the static link; reload is a desktop maintainer feature.
- **Trigger.** A `reload` command on the project's existing control channel, plus a file watch
  on the built library.

## Adoption order

1. **psxport, first consumer.**
   - Its game state is guest state.
   - Overrides are already chosen by guest address (`runtime/cpu/native_dispatch.*`).
   - Machine snapshots exist (`runtime/cpu/machine_snapshot.*`).
   - Pilot on Tomba 2; psxport's part is its `docs/plans/0201-title-hot-reload.md`.
2. **The other port frameworks**: x86port, snesport, nesport, amigaport and gcnport. Their titles
   follow.
3. **Non-port C++ products** (openSU, Lucent tools), where the state audit decides how much can
   reload.

## Phases

1. **Lucent mechanism and CMake split**, with no consumer swap yet. Proof:
   - a maintainer build of one psxport title loads its title library at startup;
   - its player build stays one static executable.
2. **psxport swap at its frame boundary.** Proof: while Tomba 2 runs, change one override's
   behaviour, rebuild the library, and the next frame shows the change without a restart.
3. **Host-side state ownership** for that title. Proof: a reload while interpolation and menus are
   active.
4. **Layout guard and fallback.** Proof: change a framework header and land on the same frame after
   the automatic restart.
5. **Every psxport title, then each port framework in the adoption order.** The `hot-reload` skill
   is written once two frameworks use the mechanism.
6. **Non-port products**, case by case.

## Progress

Not started.
