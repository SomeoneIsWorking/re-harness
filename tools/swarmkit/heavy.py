"""Machine-wide admission for heavy commands: builds, game instances, Ghidra, sweeps.

A single exclusive lock serialized every heavy job on the machine, so a one-hour
verify held back a dozen jobs that would have fit beside it. Heavy work is now
admitted through a small counting semaphore per kind (``MachineSlots``) plus a
memory reservation, reusing the swarm runner's two admission owners.

The wrapper, not the command, holds the slot and the reservation: those
descriptors are not inherited, so a daemon the command leaves behind (an
MSBuild node, a Gradle daemon) cannot keep either after the command returns.

The command runs in the wrapper's own process group rather than a new session.
A session of its own made it unreachable by every group signal aimed at the
caller, and the group kill a swarm sends a worker past its deadline is exactly
such a signal: the wrapper died, the 7 GB gate survived it and was reparented to
init. The command therefore carries ``PR_SET_PDEATHSIG`` as the other half of
the guarantee, so it also dies with a wrapper that is killed on its own. Because
the unit no longer owns a group, the reservation, the pressure watcher and the
run lifetime track the wrapper's group, which is where the command now lives.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import FrameType

from .admission import MachineSlots
from .lifetime import RunLifetime
from .pressure import PressureWatcher
from .reservations import ReservationLedger

FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
PR_SET_PDEATHSIG = 1
# 126 is the shell's "cannot execute", here "cannot arm the parent-death signal":
# the command is not safe to start without it, so the wrapper refuses rather than
# runs a gate that may outlive it.
PRCTL_FAILURE_EXIT = 126
_LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
_LIBC.prctl.argtypes = [
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
_LIBC.prctl.restype = ctypes.c_int


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
        # The unit is this group: the wrapper and the command it is about to start.
        # Adopted before the spawn, so a run that has already stopped starts nothing.
        group = os.getpgrp()
        reservation.attach(group)
        admission.pressure.adopt(group)
        lifetime.adopt(group)
        child = subprocess.Popen(
            list(argv),
            close_fds=True,
            # The one place a hook is unavoidable: nothing else can set
            # PR_SET_PDEATHSIG between the fork and the exec. It runs in the
            # single-threaded child and does nothing but prctl, getppid and
            # _exit -- no import, no allocation, no lock a killed thread could hold.
            preexec_fn=_die_with_parent(os.getpid()),  # noqa: PLW1509
        )
        previous = _forward_signals(child.pid)
        try:
            return child.wait()
        finally:
            _restore_signals(previous)
            lifetime.release(group)


def _die_with_parent(parent: int) -> Callable[[], None]:
    """Build the child's ``preexec_fn``: be SIGKILLed with the wrapper, but only if it lives."""

    def arm() -> None:
        if _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            os._exit(PRCTL_FAILURE_EXIT)
        # The wrapper can die between the fork and the prctl above, and the signal
        # that would have told the child is not delivered to one already reparented.
        # It refuses to start the command instead of becoming an orphan of it.
        if os.getppid() != parent:
            os._exit(1)

    return arm


def _forward_signals(pid: int) -> dict[int, object]:
    def forward(signum: int, _frame: FrameType | None) -> None:
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    return {signum: signal.signal(signum, forward) for signum in FORWARDED_SIGNALS}


def _restore_signals(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)  # type: ignore[arg-type]
