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
such a signal. That group signal still reaches the command, because the
wrapper's direct child is the reaper (``swarmkit.reaper``), which runs the
command in the caller's group.

The reaper is what makes the command's whole subtree die with the run.
``PR_SET_PDEATHSIG`` reaches exactly the process it is set on: a direct child of
``cmake`` lost ``ninja`` and the rest of the build when the wrapper was killed,
because each was reparented to init and kept compiling. The reaper takes that
contract instead -- a subreaper, so an orphan is reparented to it rather than to
init, and it SIGTERMs, then SIGKILLs, every remaining descendant. Because the
unit no longer owns a group, the reservation, the pressure watcher and the run
lifetime track the wrapper's group, which is where the command now lives.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from .admission import MachineSlots
from .lifetime import RunLifetime
from .peaks import PeakSampler
from .pressure import PressureWatcher
from .reaper import command_argv
from .reservations import ReservationLedger
from .worktree import WorktreeError, ccache_environment, repo_root

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
    on_peak: Callable[[int], None] | None = None,
) -> int:
    """Run ``argv`` while holding one heavy slot and its memory reservation.

    ``on_peak`` receives the command's measured peak in MiB once it exits.
    """
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
        # The wrapper's own death is the reaper's cue to take the command's
        # subtree down; the reaper arms that itself, naming this process.
        child = subprocess.Popen(
            command_argv(argv, os.getpid()), close_fds=True, env=_command_environment()
        )
        previous = _forward_signals(child.pid)
        try:
            with PeakSampler(child.pid) as sampler:
                code = child.wait()
            if on_peak is not None:
                on_peak(sampler.peak_mib)
            return code
        finally:
            _restore_signals(previous)
            lifetime.release(group)


def _command_environment() -> dict[str, str]:
    """The caller's environment, with ccache shared across worktrees of the cwd's repo.

    A CCACHE_BASEDIR the caller set wins; outside a git checkout nothing is added.
    """
    environment = dict(os.environ)
    if "CCACHE_BASEDIR" in environment:
        return environment
    try:
        root = repo_root(Path.cwd())
    except WorktreeError:
        return environment
    return environment | ccache_environment(root)


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
