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

That rule alone has no order in it, and without one it starves: a 3 GiB build
waited 27 minutes while a swarm ran eight 512 MiB workers, because every worker
that finished was replaced before the build ever saw the headroom it was waiting
for. Admission is therefore first come first served. A unit that cannot be
admitted at once leaves a waiting ticket in ``<lock-dir>/reservations/waiting/``,
and an admission is refused while any older live ticket is still queued, however
small the newcomer is. A ticket whose owner is dead is reaped when it is read, so
a crashed waiter does not hold the queue.
"""

from __future__ import annotations

import fcntl
import itertools
import json
import os
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .lifetime import RunLifetime
from .procs import MIB, group_alive, process_alive, read_group_rss, read_mem_available

POLL_SECONDS = 2.0
ENTRY_SUFFIX = ".json"
WAITING_DIRECTORY = "waiting"
_RESERVATION_COUNTER = itertools.count()
_TICKET_COUNTER = itertools.count()


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


@dataclass(frozen=True)
class WaitingTicket:
    """One queued admission: the position a unit holds in the FIFO line."""

    path: Path
    key: tuple[int, int, int]
    owner_pid: int
    reserve_mib: int
    kind: str

    def cancel(self) -> None:
        """Leave the queue: admitted, cancelled, or given up on."""
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cancel()


class ReservationLedger:
    """The shared directory of reservations plus the one rule that admits a unit."""

    def __init__(
        self,
        lock_dir: Path,
        floor_mib: int,
        reader: Callable[[], int] = read_mem_available,
        rss_reader: Callable[[Iterable[int]], dict[int, int]] = read_group_rss,
        poll_seconds: float = POLL_SECONDS,
        on_wait: Callable[[int, int, int], None] | None = None,
    ) -> None:
        self.directory = lock_dir / "reservations"
        self.waiting_directory = self.directory / WAITING_DIRECTORY
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

    def live_tickets(self) -> list[WaitingTicket]:
        """Every waiting ticket whose owner is still alive, oldest first.

        A ticket left behind by a crashed waiter is deleted here: nobody will
        ever come back for it, and left in place it would hold the whole queue.
        """
        try:
            names = sorted(self.waiting_directory.iterdir())
        except FileNotFoundError:
            return []
        tickets: list[WaitingTicket] = []
        for path in names:
            ticket = _read_ticket(path)
            if ticket is None:
                continue
            if process_alive(ticket.owner_pid):
                tickets.append(ticket)
            else:
                ticket.cancel()
        return sorted(tickets, key=lambda ticket: ticket.key)

    def queue_ahead(self, ticket: WaitingTicket | None) -> int:
        """How many live tickets this admitter is queued behind, under the lock.

        An admitter that holds no ticket yet is the newest arrival, so every
        waiting ticket is ahead of it.
        """
        with self._locked():
            return self._queue_ahead(ticket)

    def take_ticket(self, reserve_mib: int, kind: str) -> WaitingTicket:
        """Join the queue for an admission the headroom rule has not granted yet."""
        if reserve_mib < 1:
            raise ValueError("reservation must be at least 1 MiB")
        self.waiting_directory.mkdir(parents=True, exist_ok=True)
        with self._locked():
            return self._write_ticket(reserve_mib, kind)

    def try_acquire(
        self, reserve_mib: int, kind: str, ticket: WaitingTicket | None = None
    ) -> Reservation | None:
        """Take a reservation if the FIFO headroom rule allows it, else None.

        A unit is admitted only when the headroom rule holds and no live ticket
        older than its own is queued. Without ``ticket`` the admitter is the
        newest arrival, so any waiting ticket defers it.
        """
        if reserve_mib < 1:
            raise ValueError("reservation must be at least 1 MiB")
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._locked():
            if self._queue_ahead(ticket):
                return None
            outstanding = self.outstanding_bytes()
            available = self._reader()
            if available - outstanding - reserve_mib * MIB < self.floor_bytes:
                return None
            entry = self._write_entry(reserve_mib, kind)
            if ticket is not None:
                ticket.cancel()
            return entry

    def acquire(
        self, lifetime: RunLifetime, reserve_mib: int, kind: str
    ) -> Reservation:
        """Block until the FIFO headroom rule admits the unit; cancel with the run."""
        ticket: WaitingTicket | None = None
        try:
            while (entry := self.try_acquire(reserve_mib, kind, ticket)) is None:
                if ticket is None:
                    # The headroom rule refused this unit: it joins the queue now,
                    # so nothing admitted after it may take the headroom it waits for.
                    ticket = self.take_ticket(reserve_mib, kind)
                if self.on_wait is not None:
                    self.on_wait(
                        self._reader(),
                        self.outstanding_bytes() // MIB,
                        self.queue_ahead(ticket),
                    )
                lifetime.pause(self.poll_seconds)
            return entry
        except BaseException:
            if ticket is not None:
                ticket.cancel()
            raise

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """The one flock that makes a check and the write it justifies atomic."""
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _queue_ahead(self, ticket: WaitingTicket | None) -> int:
        waiting = self.live_tickets()
        if ticket is None:
            return len(waiting)
        return sum(1 for other in waiting if other.key < ticket.key)

    def _write_entry(self, reserve_mib: int, kind: str) -> Reservation:
        pid = os.getpid()
        path = self.directory / f"{pid}.{next(_RESERVATION_COUNTER)}{ENTRY_SUFFIX}"
        entry = Reservation(path, pid, reserve_mib, kind)
        entry.write()
        return entry

    def _write_ticket(self, reserve_mib: int, kind: str) -> WaitingTicket:
        pid = os.getpid()
        since = time.time_ns()
        counter = next(_TICKET_COUNTER)
        path = self.waiting_directory / f"{since}.{pid}.{counter}{ENTRY_SUFFIX}"
        ticket = WaitingTicket(path, (since, pid, counter), pid, reserve_mib, kind)
        _write_ticket_record(path, pid, reserve_mib, kind, since)
        return ticket


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


def _write_ticket_record(
    path: Path, pid: int, reserve_mib: int, kind: str, since: int
) -> None:
    record = {"pid": pid, "reserve_mib": reserve_mib, "kind": kind, "since": since}
    # Renamed into place, like an entry: a reader sees the whole ticket or none.
    scratch = path.with_suffix(".new")
    scratch.write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def _read_ticket(path: Path) -> WaitingTicket | None:
    """The ticket in ``path``, or None when it is not one this ledger can order.

    The order lives in the name (``<since-ns>.<pid>.<counter>``), because arrival
    time is what FIFO means here; the record says who is waiting and for what.
    """
    if path.suffix != ENTRY_SUFFIX:
        return None
    try:
        since, pid, counter = (int(part) for part in path.stem.split("."))
        record = json.loads(path.read_text(encoding="utf-8"))
        return WaitingTicket(
            path=path,
            key=(since, pid, counter),
            owner_pid=int(record["pid"]),
            reserve_mib=int(record["reserve_mib"]),
            kind=str(record["kind"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
