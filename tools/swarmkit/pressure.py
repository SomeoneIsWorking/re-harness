"""Pause the newest work unit on the machine while the host is really out of memory.

This is the one memory countermeasure. Nothing is admitted or queued ahead of
time; the guard reads ``MemAvailable`` and, when it falls below ``pause_mib``,
SIGSTOPs the most recently started running unit from the registry (``units``).
It never stops the last running unit.

A stop does not free memory, it only stops growth, so available memory stays
low after a pause. The first guard paused a further unit every poll while it
did, and within seconds kept ~19 units stopped at once for ~100 s each (250
pause/resume cycles in 20 minutes on 2026-09-30), then resumed them all at once
and started over. Now, within ``settle_seconds`` of its last pause it pauses
again only if memory kept falling past that pause's reading or reached
``critical_mib``; and above ``resume_mib`` it resumes one unit, the oldest
stopped, per ``settle_seconds``. Time spent stopped is not work, so a swarm
unit's deadline is extended by it (``process``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from signal import SIGCONT, SIGSTOP

from .lifetime import signal_group
from .procs import MIB, read_mem_available


@dataclass
class PressureGuard:
    """Decides, one poll at a time, which of the machine's units to stop or resume."""

    pause_mib: int
    resume_mib: int
    critical_mib: int
    settle_seconds: float
    reader: Callable[[], int] = read_mem_available
    stopper: Callable[[int, int], None] = signal_group
    clock: Callable[[], float] = time.monotonic
    # Groups this guard has stopped and not yet resumed, in the order it stopped them.
    stopped: list[int] = field(default_factory=list)
    _last_action: float = float("-inf")
    _last_pause_bytes: int | None = None

    def poll(self, groups: Sequence[int]) -> list[str]:
        """Take one decision over ``groups`` (live units, oldest first); return its events."""
        live = set(groups)
        self.stopped = [group for group in self.stopped if group in live]
        available = self.reader()
        settled = self.clock() - self._last_action >= self.settle_seconds
        if available > self.resume_mib * MIB:
            self._last_pause_bytes = None
            if self.stopped and settled:
                return [self._resume(self._oldest_stopped(groups), available)]
            return []
        if available < self.pause_mib * MIB and self._may_pause(available, settled):
            running = [group for group in groups if group not in self.stopped]
            if len(running) > 1:
                self.stopper(running[-1], SIGSTOP)
                self.stopped.append(running[-1])
                self._last_action = self.clock()
                self._last_pause_bytes = available
                return [_event("paused", running[-1], available)]
        return []

    def _may_pause(self, available: int, settled: bool) -> bool:
        if available < self.critical_mib * MIB or self._last_pause_bytes is None:
            return True
        # Still falling past the last pause's reading: that pause did not stop the growth.
        return settled and available < self._last_pause_bytes

    def _oldest_stopped(self, groups: Sequence[int]) -> int:
        return next(group for group in groups if group in self.stopped)

    def _resume(self, group: int, available: int) -> str:
        self.stopper(group, SIGCONT)
        self.stopped.remove(group)
        self._last_action = self.clock()
        return _event("resumed", group, available)

    def resume_all(self) -> list[str]:
        """SIGCONT every group this guard stopped: its last act when it exits."""
        available = self.reader()
        events = [self._resume(group, available) for group in list(self.stopped)]
        return events


def _event(action: str, group: int, available: int) -> str:
    return (
        f"pressure: {action} process group {group}; MemAvailable {available // MIB} MiB"
    )
