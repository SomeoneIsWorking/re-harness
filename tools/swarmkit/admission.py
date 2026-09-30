"""Machine-wide slot ownership shared by every concurrent swarm invocation.

Slots are ``count`` lock files in one shared directory; holding an exclusive
``flock`` on any one of them is holding a slot. The kernel drops the lock when
the holder exits, however it exits, so a crashed swarm never leaks a slot.
Slots cap how many units run, not how much memory they take; the memory rule
lives with its data in ``reservations``.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Self

from .lifetime import RunLifetime

POLL_SECONDS = 2.0


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
