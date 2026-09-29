"""Machine-wide admission for heavy commands: builds, game instances, Ghidra, sweeps.

A single exclusive lock serialized every heavy job on the machine, so a one-hour
verify held back a dozen jobs that would have fit beside it. Heavy work is now
admitted through a small counting semaphore per kind (``MachineSlots``) plus a
``MemAvailable`` floor, reusing the swarm runner's admission owner.

The wrapper, not the command, holds the slot: the slot descriptor is not
inherited, so a daemon the command leaves behind (an MSBuild node, a Gradle
daemon) cannot keep a slot after the command returns. Termination signals are
forwarded to the command's process group.
"""

from __future__ import annotations

import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import FrameType

from .admission import MachineSlots, MemoryFloor, SlotLease
from .lifetime import RunLifetime, signal_group

FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@dataclass(frozen=True)
class HeavyAdmission:
    """The slots and memory floor one heavy kind is admitted through."""

    slots: MachineSlots
    floor: MemoryFloor

    def admit(self, lifetime: RunLifetime, on_wait: Callable[[], None]) -> SlotLease:
        """Block until a slot is free and memory is above the floor; return the held slot."""
        lease = self.slots.try_acquire()
        if lease is None:
            on_wait()
            lease = self.slots.acquire(lifetime)
        try:
            self.floor.wait(lifetime)
        except BaseException:
            lease.release()
            raise
        return lease


def run_admitted(
    admission: HeavyAdmission,
    argv: Sequence[str],
    lifetime: RunLifetime,
    on_wait: Callable[[], None],
) -> int:
    """Run ``argv`` while holding one heavy slot; return its exit status."""
    with admission.admit(lifetime, on_wait):
        child = subprocess.Popen(list(argv), start_new_session=True)
        lifetime.adopt(child.pid)
        previous = _forward_signals(child.pid)
        try:
            return child.wait()
        finally:
            _restore_signals(previous)
            lifetime.release(child.pid)


def _forward_signals(group: int) -> dict[int, object]:
    def forward(signum: int, _frame: FrameType | None) -> None:
        signal_group(group, signum)

    return {signum: signal.signal(signum, forward) for signum in FORWARDED_SIGNALS}


def _restore_signals(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)  # type: ignore[arg-type]
