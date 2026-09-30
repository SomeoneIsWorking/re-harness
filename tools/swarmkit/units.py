"""The machine-wide registry of running work units, read by the pressure guard.

Nothing waits to be admitted. A unit (a swarm worker or gate, a heavy.py command)
starts at once and writes one entry into ``<lock-dir>/units/`` naming its process
group; the pressure guard (``guard``) reads the entries to know which groups it
may pause when the host actually runs short of memory, newest first. Predicted
admission was removed on 2026-09-30: per-kind slots and reserved peaks (3 GiB
per build, against measured compiles of 400 MiB) queued builds for up to 50
minutes while the host had 7 GiB free and half its cores idle.

An entry whose group is gone is ignored and pruned, so a crashed unit never
leaves the guard a stale target.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .procs import group_alive

UNITS_DIRECTORY = "units"


@dataclass(frozen=True)
class Unit:
    group: int
    kind: str
    started_ns: int
    path: Path


class UnitRegistry:
    def __init__(self, lock_dir: Path) -> None:
        self.directory = lock_dir / UNITS_DIRECTORY

    def register(self, group: int, kind: str) -> Unit:
        """Record ``group`` as a live unit; the entry is this process's until ``remove``.

        One group can be registered more than once (a swarm gate that calls
        heavy.py), so each entry is named by its group, registrant and start.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        started_ns = time.time_ns()
        name = f"{group}-{os.getpid()}-{started_ns}.json"
        unit = Unit(group, kind, started_ns, self.directory / name)
        temporary = unit.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"group": group, "kind": kind, "started_ns": unit.started_ns}),
            encoding="utf-8",
        )
        temporary.replace(unit.path)
        return unit

    def remove(self, unit: Unit) -> None:
        unit.path.unlink(missing_ok=True)

    def live(self) -> list[Unit]:
        """Every live unit, oldest first, one per group; dead entries are deleted."""
        units: dict[int, Unit] = {}
        for path in self.directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            group = int(record["group"])
            if not group_alive(group):
                path.unlink(missing_ok=True)
                continue
            unit = Unit(group, record["kind"], int(record["started_ns"]), path)
            if group not in units or unit.started_ns < units[group].started_ns:
                units[group] = unit
        return sorted(units.values(), key=lambda unit: unit.started_ns)
