"""Pause the newest work unit on the machine while the host is really out of memory.

This is the one memory countermeasure. Nothing is admitted or queued ahead of
time; the guard reads ``MemAvailable`` and, only when it falls below
``pause_mib``, SIGSTOPs the most recently started running unit from the
registry (``units``). A stopped unit's pages can go to swap while the older
units finish. Once memory is back above ``resume_mib`` every stopped unit is
SIGCONTed. The gap is the hysteresis that stops a host hovering at the threshold
from pausing and resuming forever. It never stops the last running unit: with
nothing else left to pause, ending it is the operator's call, not the guard's.
Time spent stopped is not work, so a swarm unit's deadline is extended by it
(``process``).
"""

from __future__ import annotations

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
    reader: Callable[[], int] = read_mem_available
    stopper: Callable[[int, int], None] = signal_group
    # Groups this guard has stopped and not yet resumed.
    stopped: set[int] = field(default_factory=set)

    def poll(self, groups: Sequence[int]) -> list[str]:
        """Take one decision over ``groups`` (live units, oldest first); return its events."""
        self.stopped &= set(groups)
        available = self.reader()
        if available > self.resume_mib * MIB:
            return self.resume_all(available)
        if available < self.pause_mib * MIB:
            running = [group for group in groups if group not in self.stopped]
            if len(running) > 1:
                self.stopper(running[-1], SIGSTOP)
                self.stopped.add(running[-1])
                return [_event("paused", running[-1], available)]
        return []

    def resume_all(self, available: int | None = None) -> list[str]:
        """SIGCONT every group this guard stopped (also its last act when it exits)."""
        available = self.reader() if available is None else available
        events = []
        for group in sorted(self.stopped):
            self.stopper(group, SIGCONT)
            events.append(_event("resumed", group, available))
        self.stopped.clear()
        return events


def _event(action: str, group: int, available: int) -> str:
    return (
        f"pressure: {action} process group {group}; MemAvailable {available // MIB} MiB"
    )
