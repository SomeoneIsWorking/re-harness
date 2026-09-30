"""Run one child in its own process group with a hard deadline.

The group is the unit of ownership: on timeout the whole group is terminated by
its captured id, and any members left behind after a normal exit are reaped the
same way. Nothing here matches processes by name.

A unit paused by the pressure watcher (``pressure``) is not working, so the
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
from .procs import group_stopped

LAUNCH_FAILURE_CODE = 127
TERMINATE_GRACE_SECONDS = 5.0
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

    ``on_spawn`` receives the new process group, which is the unit a memory
    reservation and the pressure watcher own.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Some CLIs (opencode) resolve paths from $PWD rather than getcwd(); keep them in agreement.
    environment = dict(os.environ, **(extra_env or {}), PWD=str(cwd))
    with open(log_path, "wb") as log:
        try:
            child = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            log.write(f"swarm: could not launch {argv[0]!r}: {error}\n".encode())
            return ProcessOutcome(LAUNCH_FAILURE_CODE, False, log_path)
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
