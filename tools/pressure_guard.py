#!/usr/bin/env python3
"""Pause the machine's newest work unit while memory is really short; resume it after.

    pressure_guard.py [--lock-dir DIR] [--once]

Runs as the systemd user service ``pressure-guard`` (see skills/global/swarm/SKILL.md,
"Memory"). Every poll it reads the unit registry, pauses or resumes, and touches
``<lock-dir>/guard/heartbeat`` so the watchdog can tell it is alive. On start it
resumes every registered unit, because a guard that died cannot remember which
units it stopped; on exit it resumes the ones it stopped.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

if not sys.platform.startswith("linux"):
    sys.exit("pressure_guard: refused: Linux-only (/proc/meminfo, process groups)")

from swarmkit import config
from swarmkit.console import emit
from swarmkit.lifetime import signal_group
from swarmkit.pressure import PressureGuard
from swarmkit.units import UnitRegistry

POLL_SECONDS = 0.5


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="pressure_guard.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--lock-dir", type=Path, default=None)
    parser.add_argument(
        "--once", action="store_true", help="take one decision and exit"
    )
    args = parser.parse_args(argv)
    lock_dir = (args.lock_dir or config.default_lock_dir()).resolve()
    registry = UnitRegistry(lock_dir)
    heartbeat = config.guard_heartbeat(lock_dir)
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    guard = PressureGuard(
        config.PRESSURE_PAUSE_MIB,
        config.PRESSURE_RESUME_MIB,
        config.PRESSURE_CRITICAL_MIB,
        config.PRESSURE_SETTLE_SECONDS,
    )
    for unit in registry.live():
        signal_group(unit.group, signal.SIGCONT)
    finished = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _signum, _frame: finished.set())
    try:
        while True:
            for line in guard.poll([unit.group for unit in registry.live()]):
                emit(line)
            heartbeat.touch()
            if args.once or finished.wait(POLL_SECONDS):
                return 0
    finally:
        for line in guard.resume_all():
            emit(line)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
