"""Run one child in its own process group with a hard deadline.

The group is the unit of ownership: on timeout the whole group is terminated by
its captured id, and any members left behind after a normal exit are reaped the
same way. Nothing here matches processes by name.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .lifetime import RunInterrupted, RunLifetime, signal_group

LAUNCH_FAILURE_CODE = 127
TERMINATE_GRACE_SECONDS = 5.0


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
) -> ProcessOutcome:
    """Run ``argv`` in ``cwd`` with stdout+stderr in ``log_path``; kill its group on timeout."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Some CLIs (opencode) resolve paths from $PWD rather than getcwd(); keep them in agreement.
    environment = dict(os.environ, PWD=str(cwd))
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
        returncode = child.wait(timeout=timeout)
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
