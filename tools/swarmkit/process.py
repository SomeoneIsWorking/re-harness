"""Run one child in its own process group with a hard deadline.

The group is the unit of ownership: on timeout the whole group is terminated by
its captured id, and any members left behind after a normal exit are reaped the
same way. Nothing here matches processes by name.

The group alone is not the whole subtree. A worker that starts a helper with
``setsid`` or ``nohup ... &`` (opencode writes retry scripts into /tmp and runs
them detached) moves it out of the group, and a group kill never reaches it. So
the child is always the reaper (``reaper``): a subreaper that adopts every
orphan below it and takes the whole parent-graph subtree down when the command
ends, and dies with the runner thread that started it. On a timeout the runner
also kills that subtree itself, in case the reaper is killed before it finishes.

A unit paused by the pressure guard (``pressure``) is not working, so the
deadline is extended by every slice it spends stopped; a unit stopped just before
its deadline still gets its full budget of running time.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .lifetime import RunInterrupted, RunLifetime, signal_group
from .procs import descendants, group_stopped
from .reaper import TERM_GRACE_SECONDS as REAPER_GRACE_SECONDS
from .reaper import command_argv

# The command's own grace plus the reaper's grace for what it leaves behind.
TERMINATE_GRACE_SECONDS = 5.0 + REAPER_GRACE_SECONDS
# Short enough that a pause is noticed before the deadline passes, long enough
# that the poll itself is not measurable next to the child's work.
STOP_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class ProcessOutcome:
    """How a bounded child ended; ``returncode`` is None only when it timed out."""

    returncode: int | None
    timed_out: bool
    log_path: Path

    def tail(self, max_lines: int = 60, max_chars: int = 4000) -> str:
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()[-max_lines:]
        return "\n".join(lines)[-max_chars:]


def run_bounded(
    argv: Sequence[str],
    cwd: Path,
    timeout: float,
    log_path: Path,
    lifetime: RunLifetime,
    extra_env: Mapping[str, str] | None = None,
    on_spawn: Callable[[int], None] | None = None,
) -> ProcessOutcome:
    """Run ``argv`` in ``cwd`` with stdout+stderr in ``log_path``; kill its group on timeout.

    ``on_spawn`` receives the new process group, the unit the pressure guard may pause.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Some CLIs (opencode) resolve paths from $PWD rather than getcwd(); keep them in agreement.
    environment = dict(os.environ, **(extra_env or {}), PWD=str(cwd))
    with open(log_path, "wb") as log:
        child = subprocess.Popen(
            command_argv(argv, os.getpid()),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        group = child.pid
        if on_spawn is not None:
            on_spawn(group)
        try:
            lifetime.adopt(group)
        except RunInterrupted:
            child.wait()
            raise
        try:
            return _wait(child, group, timeout, log, log_path, lifetime)
        finally:
            lifetime.release(group)


def _wait(
    child: subprocess.Popen,
    group: int,
    timeout: float,
    log,
    log_path: Path,
    lifetime: RunLifetime,
) -> ProcessOutcome:
    try:
        returncode = _wait_unpaused(child, group, timeout)
    except subprocess.TimeoutExpired:
        signal_group(group, signal.SIGTERM)
        try:
            child.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_subtree(child.pid)
            signal_group(group, signal.SIGKILL)
            child.wait()
        signal_group(group, signal.SIGKILL)
        log.write(
            f"\nswarm: killed process group {group} after {timeout:g}s\n".encode()
        )
        return ProcessOutcome(None, True, log_path)
    # A worker may leave helpers (a private model server, a build daemon) in its group.
    signal_group(group, signal.SIGKILL)
    if lifetime.stopped:
        raise RunInterrupted(f"process group {group} stopped with the run")
    return ProcessOutcome(returncode, False, log_path)


def _wait_unpaused(child: subprocess.Popen, group: int, timeout: float) -> int:
    """``child.wait(timeout=...)`` with the time the group spent stopped added back."""
    budget = timeout
    while True:
        started = time.monotonic()
        try:
            return child.wait(timeout=min(budget, STOP_POLL_SECONDS))
        except subprocess.TimeoutExpired:
            pass
        spent = time.monotonic() - started
        if group_stopped(group):
            budget += spent
        else:
            budget -= spent
        if budget <= 0:
            raise subprocess.TimeoutExpired(list(child.args), timeout)


def _kill_subtree(pid: int) -> None:
    """SIGKILL every descendant of ``pid`` by the parent graph, sessions included."""
    for member in descendants(pid):
        try:
            os.kill(member, signal.SIGKILL)
        except ProcessLookupError:
            pass
