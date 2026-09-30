"""Machine-wide memory reservations: a unit declares its peak, the host keeps the headroom.

A flock'd slot file caps concurrency but says nothing about size, so a swarm
admitted eight workers while the host looked free and every one of them then grew
to its peak (a gate build, a game run) until the OOM reaper took the run. Each
admitted unit now writes one entry into ``<lock-dir>/reservations/`` reserving the
memory it may still grow into, and a new unit starts only if
``MemAvailable - outstanding - reserve_new`` stays above the floor. An entry's
outstanding part shrinks as the unit's own process group actually reaches its
reserve, and an entry whose process group is gone is ignored, so a crashed
admitter never leaks a reservation.
"""

from __future__ import annotations

import fcntl
import itertools
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .lifetime import RunLifetime
from .procs import MIB, group_alive, process_alive, read_group_rss, read_mem_available

POLL_SECONDS = 2.0
ENTRY_SUFFIX = ".json"
_RESERVATION_COUNTER = itertools.count()


@dataclass
class Reservation:
    """One live entry in the ledger: the peak a unit may still grow into."""

    path: Path
    owner_pid: int
    reserve_mib: int
    kind: str
    group: int = 0

    def attach(self, group: int) -> None:
        """Name the unit's process group, so its consumed part stops counting."""
        self.group = group
        self.write()

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def write(self) -> None:
        record = {
            "pid": self.owner_pid,
            "pgid": self.group,
            "reserve_mib": self.reserve_mib,
            "kind": self.kind,
        }
        # Renamed into place: a concurrent admitter reading the directory must see
        # the whole record or none of it, never half of one.
        scratch = self.path.with_suffix(".new")
        scratch.write_text(json.dumps(record) + "\n", encoding="utf-8")
        os.replace(scratch, self.path)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class ReservationLedger:
    """The shared directory of reservations plus the one rule that admits a unit."""

    def __init__(
        self,
        lock_dir: Path,
        floor_mib: int,
        reader: Callable[[], int] = read_mem_available,
        rss_reader: Callable[[Iterable[int]], dict[int, int]] = read_group_rss,
        poll_seconds: float = POLL_SECONDS,
        on_wait: Callable[[int, int], None] | None = None,
    ) -> None:
        self.directory = lock_dir / "reservations"
        self.lock_path = lock_dir / "reservations.lock"
        self.floor_mib = floor_mib
        self._reader = reader
        self._rss_reader = rss_reader
        self.poll_seconds = poll_seconds
        self.on_wait = on_wait

    @property
    def floor_bytes(self) -> int:
        return self.floor_mib * MIB

    def live_entries(self) -> list[Reservation]:
        """Every entry whose owning process group still exists, oldest name first.

        An entry left behind by a crashed admitter is deleted here: its group is
        gone, so it constrains nothing and would only accumulate.
        """
        try:
            names = sorted(self.directory.iterdir())
        except FileNotFoundError:
            return []
        entries: list[Reservation] = []
        for path in names:
            entry = _read_entry(path)
            if entry is None:
                continue
            if _entry_alive(entry):
                entries.append(entry)
            else:
                path.unlink(missing_ok=True)
        return entries

    def outstanding_bytes(self) -> int:
        """The part of every live reservation its unit has not consumed yet.

        A unit whose process group is not attached yet has consumed nothing: it
        has been admitted and is about to start.
        """
        entries = self.live_entries()
        started = [entry for entry in entries if entry.group]
        used = self._rss_reader(entry.group for entry in started)
        total = sum(entry.reserve_mib for entry in entries if not entry.group)
        for entry in started:
            rss_mib = used.get(entry.group, 0) // MIB
            total += max(0, entry.reserve_mib - rss_mib)
        return total * MIB

    def try_acquire(self, reserve_mib: int, kind: str) -> Reservation | None:
        """Take a reservation if the headroom rule allows it, else return None."""
        if reserve_mib < 1:
            raise ValueError("reservation must be at least 1 MiB")
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            outstanding = self.outstanding_bytes()
            available = self._reader()
            if available - outstanding - reserve_mib * MIB < self.floor_bytes:
                return None
            return self._write_entry(reserve_mib, kind)
        finally:
            os.close(descriptor)

    def acquire(
        self, lifetime: RunLifetime, reserve_mib: int, kind: str
    ) -> Reservation:
        """Block until the headroom rule admits the unit; cancel with the run."""
        while (entry := self.try_acquire(reserve_mib, kind)) is None:
            if self.on_wait is not None:
                self.on_wait(self._reader(), self.outstanding_bytes() // MIB)
            lifetime.pause(self.poll_seconds)
        return entry

    def _write_entry(self, reserve_mib: int, kind: str) -> Reservation:
        pid = os.getpid()
        path = self.directory / f"{pid}.{next(_RESERVATION_COUNTER)}{ENTRY_SUFFIX}"
        entry = Reservation(path, pid, reserve_mib, kind)
        entry.write()
        return entry


def _entry_alive(entry: Reservation) -> bool:
    """Before a group is attached the admitting process itself is the claim."""
    return group_alive(entry.group) if entry.group else process_alive(entry.owner_pid)


def _read_entry(path: Path) -> Reservation | None:
    if path.suffix != ENTRY_SUFFIX:
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return Reservation(
            path=path,
            owner_pid=int(record["pid"]),
            reserve_mib=int(record["reserve_mib"]),
            kind=str(record["kind"]),
            group=int(record.get("pgid", 0)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
