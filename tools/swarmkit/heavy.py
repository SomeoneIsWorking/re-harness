"""Machine-wide admission for heavy commands: builds, game instances, Ghidra, sweeps.

A single exclusive lock serialized every heavy job on the machine, so a one-hour
verify held back a dozen jobs that would have fit beside it. Heavy work is now
admitted through a small counting semaphore per kind (``MachineSlots``) plus a
memory reservation, reusing the swarm runner's two admission owners.

The wrapper, not the command, holds the slot and the reservation: those
descriptors are not inherited, so a daemon the command leaves behind (an
MSBuild node, a Gradle daemon) cannot keep either after the command returns.
Termination signals are forwarded to the command's process group.
"""

from __future__ import annotations

import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import FrameType

from .admission import MachineSlots
from .lifetime import RunLifetime, signal_group
from .pressure import PressureWatcher
from .reservations import ReservationLedger

FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@dataclass(frozen=True)
class HeavyAdmission:
    """The slots, the memory reservation, and the watcher one heavy kind is admitted through."""

    slots: MachineSlots
    memory: ReservationLedger
    reserve_mib: int
    kind: str
    pressure: PressureWatcher


def run_admitted(
    admission: HeavyAdmission,
    argv: Sequence[str],
    lifetime: RunLifetime,
    on_wait: Callable[[], None],
) -> int:
    """Run ``argv`` while holding one heavy slot and its memory reservation."""
    lease = admission.slots.try_acquire()
    if lease is None:
        on_wait()
        lease = admission.slots.acquire(lifetime)
    with lease, admission.memory.acquire(
        lifetime, admission.reserve_mib, admission.kind
    ) as reservation:
        child = subprocess.Popen(list(argv), start_new_session=True)
        reservation.attach(child.pid)
        admission.pressure.adopt(child.pid)
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
