"""Pause the newest of this process's own units while the host is out of memory.

A reservation keeps admission honest, but a host can still be squeezed by work
this swarm does not own (another session's build, the page cache). Rather than
let the OOM reaper kill a run mid-write, a watcher in the admitting process polls
``MemAvailable`` and SIGSTOPs the most recently admitted unit it still owns while
the host is under pressure, then SIGCONTs the stopped groups oldest first once
memory comes back. It never stops the last running unit: with nothing else left
to pause, ending the run is the operator's call, not the watcher's. Time spent
stopped is not work, so the unit's deadline is extended by it (``process``).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from signal import SIGCONT, SIGSTOP

from .lifetime import signal_group
from .procs import MIB, group_alive, read_mem_available

POLL_SECONDS = 2.0


@dataclass
class PressureWatcher:
    """Stops and resumes this process's own units as the host's memory comes and goes."""

    pause_mib: int
    resume_mib: int
    reader: Callable[[], int] = read_mem_available
    poll_seconds: float = POLL_SECONDS
    on_event: Callable[[str], None] | None = None
    stopper: Callable[[int, int], None] = signal_group
    # Live units, oldest first, mapped to whether they are currently stopped.
    _units: dict[int, bool] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _finished: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def adopt(self, group: int) -> None:
        """Register a just-started process group as this process's newest unit."""
        with self._lock:
            if group not in self._units:
                self._units[group] = False

    def _drop_exited(self) -> None:
        """Forget units that have ended, so they are neither stopped nor counted."""
        with self._lock:
            for group in [g for g in self._units if not group_alive(g)]:
                del self._units[group]

    def poll(self) -> list[str]:
        """Take one decision; the returned strings are the events it emitted."""
        self._drop_exited()
        available = self.reader()
        if available > self.resume_mib * MIB:
            return self._resume(available)
        if available < self.pause_mib * MIB:
            return self._pause(available)
        return []

    def _pause(self, available: int) -> list[str]:
        with self._lock:
            running = [group for group, stopped in self._units.items() if not stopped]
            if len(running) <= 1:
                return []
            group = running[-1]
            self._units[group] = True
        self.stopper(group, SIGSTOP)
        return [self._event("paused", group, available)]

    def _resume(self, available: int) -> list[str]:
        with self._lock:
            stopped = [group for group, stopped in self._units.items() if stopped]
            for group in stopped:
                self._units[group] = False
        for group in stopped:
            self.stopper(group, SIGCONT)
        return [self._event("resumed", group, available) for group in stopped]

    def _event(self, action: str, group: int, available: int) -> str:
        line = (
            f"pressure: {action} process group {group}; "
            f"MemAvailable {available // MIB} MiB"
        )
        if self.on_event is not None:
            self.on_event(line)
        return line

    def start(self) -> None:
        """Run the poll loop in a daemon thread until ``stop``."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="pressure-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if (thread := self._thread) is not None:
            self._finished.set()
            thread.join(timeout=self.poll_seconds * 4)
            self._thread = None

    def _loop(self) -> None:
        while not self._finished.wait(self.poll_seconds):
            try:
                self.poll()
            except OSError:
                continue
