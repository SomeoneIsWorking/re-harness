"""Run one heavy command (a build, a game instance, Ghidra, a sweep) as a guarded unit.

Nothing waits to start. The command's group is registered as a unit, so the
pressure guard (``pressure``) can pause it if the host really runs out of memory;
per-kind slots and predicted memory reservations were removed on 2026-09-30,
after they queued builds for up to 50 minutes with 7 GiB free and cores idle.

The wrapper, not the command, owns the registry entry, so a daemon the command
leaves behind (an MSBuild node, a Gradle daemon) does not keep it.

The command runs in the wrapper's own process group rather than a new session.
A session of its own made it unreachable by every group signal aimed at the
caller, and the group kill a swarm sends a worker past its deadline is exactly
such a signal. That group signal still reaches the command, because the
wrapper's direct child is the reaper (``swarmkit.reaper``), which runs the
command in the caller's group.

The reaper is what makes the command's whole subtree die with the run.
``PR_SET_PDEATHSIG`` reaches exactly the process it is set on: a direct child of
``cmake`` lost ``ninja`` and the rest of the build when the wrapper was killed,
because each was reparented to init and kept compiling. The reaper takes that
contract instead -- a subreaper, so an orphan is reparented to it rather than to
init, and it SIGTERMs, then SIGKILLs, every remaining descendant. Because the
unit no longer owns a group, the registry entry and the run lifetime track the
wrapper's group, which is where the command now lives.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from .lifetime import RunLifetime
from .reaper import command_argv
from .units import UnitRegistry
from .worktree import WorktreeError, ccache_environment, repo_root

FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def run_unit(
    registry: UnitRegistry,
    kind: str,
    argv: Sequence[str],
    lifetime: RunLifetime,
) -> int:
    """Run ``argv`` at once as a registered unit of ``kind``; return its exit status."""
    # The unit is this group: the wrapper and the command it is about to start.
    # Adopted before the spawn, so a run that has already stopped starts nothing.
    group = os.getpgrp()
    unit = registry.register(group, kind)
    try:
        lifetime.adopt(group)
        # The wrapper's own death is the reaper's cue to take the command's
        # subtree down; the reaper arms that itself, naming this process.
        child = subprocess.Popen(
            command_argv(argv, os.getpid()), close_fds=True, env=_command_environment()
        )
        previous = _forward_signals(child.pid)
        try:
            return child.wait()
        finally:
            _restore_signals(previous)
            lifetime.release(group)
    finally:
        registry.remove(unit)


def _command_environment() -> dict[str, str]:
    """The caller's environment, with ccache shared across worktrees of the cwd's repo.

    A CCACHE_BASEDIR the caller set wins; outside a git checkout nothing is added.
    """
    environment = dict(os.environ)
    if "CCACHE_BASEDIR" in environment:
        return environment
    try:
        root = repo_root(Path.cwd())
    except WorktreeError:
        return environment
    return environment | ccache_environment(root)


def _forward_signals(pid: int) -> dict[int, object]:
    def forward(signum: int, _frame: FrameType | None) -> None:
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    return {signum: signal.signal(signum, forward) for signum in FORWARDED_SIGNALS}


def _restore_signals(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)  # type: ignore[arg-type]
