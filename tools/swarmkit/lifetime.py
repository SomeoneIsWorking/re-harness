"""Bounds every child and wait of one run to the run's own lifetime.

An interrupted run (Ctrl-C, SIGTERM) calls ``stop``: every live worker/gate
process group is terminated by its captured id, waits give up,
and no new child starts. Jobs cut short raise ``RunInterrupted`` and write no
verdict, so ``report`` counts them as unfinished rather than as a failure the
worker never made.
"""

from __future__ import annotations

import os
import signal
import threading


class RunInterrupted(RuntimeError):
    """The run was stopped; the job has no verdict."""


class RunLifetime:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._groups: set[int] = set()
        self._stopped = threading.Event()

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def adopt(self, group: int) -> None:
        """Track a just-started process group; kill it at once if the run already stopped."""
        with self._lock:
            if self._stopped.is_set():
                signal_group(group, signal.SIGKILL)
                raise RunInterrupted("run stopped")
            self._groups.add(group)

    def release(self, group: int) -> None:
        with self._lock:
            self._groups.discard(group)

    def pause(self, seconds: float) -> None:
        """Sleep for a poll interval, or raise at once when the run stops."""
        if self._stopped.wait(seconds):
            raise RunInterrupted("run stopped")

    def stop(self) -> None:
        with self._lock:
            self._stopped.set()
            groups = list(self._groups)
        for group in groups:
            signal_group(group, signal.SIGTERM)


def signal_group(group: int, signum: int) -> None:
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass
