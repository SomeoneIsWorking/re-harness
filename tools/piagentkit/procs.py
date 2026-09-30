"""Process liveness and termination, always by captured pid.

Nothing here matches a process by name: a shared ``pi`` binary belongs to other
agents and to the operator's own session, so every signal goes to a pid this
tool started and recorded.
"""

from __future__ import annotations

import os
import signal
import time

from swarmkit.procs import process_running

from .config import TERMINATE_GRACE_SECONDS


def pid_alive(pid: int | None) -> bool:
    """True when ``pid`` is a live process; a reaped zombie counts as gone."""
    return pid is not None and pid > 0 and process_running(pid)


def terminate(pid: int | None, grace: float = TERMINATE_GRACE_SECONDS) -> None:
    """SIGTERM ``pid``, then SIGKILL it if it outlives ``grace`` seconds."""
    if not pid_alive(pid):
        return
    assert pid is not None
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.time() + grace
    while time.time() < deadline and pid_alive(pid):
        time.sleep(0.05)
