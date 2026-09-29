"""Machine-wide admission control shared by every concurrent swarm invocation.

Slots are ``count`` lock files in one shared directory; holding an exclusive
``flock`` on any one of them is holding a slot. The kernel drops the lock when
the holder exits, however it exits, so a crashed swarm never leaks a slot.
Independently, no worker starts while ``MemAvailable`` is below the floor.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .lifetime import RunLifetime

POLL_SECONDS = 2.0
MIB = 1024 * 1024


class SlotLease:
    """An exclusive hold on one slot file, released by ``release`` or leaving the ``with``."""

    def __init__(self, descriptor: int, path: Path) -> None:
        self._descriptor: int | None = descriptor
        self.path = path

    def release(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class MachineSlots:
    """A counting semaphore of ``count`` flock'd files under ``directory``."""

    def __init__(
        self, directory: Path, count: int, poll_seconds: float = POLL_SECONDS
    ) -> None:
        if count < 1:
            raise ValueError("slot count must be at least 1")
        self.directory = directory
        self.count = count
        self.poll_seconds = poll_seconds

    def try_acquire(self) -> SlotLease | None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for index in range(self.count):
            path = self.directory / f"slot-{index:03d}.lock"
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                continue
            return SlotLease(descriptor, path)
        return None

    def acquire(self, lifetime: RunLifetime) -> SlotLease:
        while True:
            lease = self.try_acquire()
            if lease is not None:
                return lease
            lifetime.pause(self.poll_seconds)


def read_mem_available() -> int:
    """``MemAvailable`` from ``/proc/meminfo`` in bytes."""
    with open("/proc/meminfo", encoding="ascii") as meminfo:
        for line in meminfo:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo has no MemAvailable line")


@dataclass
class MemoryFloor:
    """Blocks a new worker until at least ``floor_bytes`` of memory is available."""

    floor_bytes: int
    reader: Callable[[], int] = read_mem_available
    poll_seconds: float = POLL_SECONDS
    on_wait: Callable[[int], None] | None = None

    def wait(self, lifetime: RunLifetime) -> None:
        while (available := self.reader()) < self.floor_bytes:
            if self.on_wait is not None:
                self.on_wait(available)
            lifetime.pause(self.poll_seconds)
