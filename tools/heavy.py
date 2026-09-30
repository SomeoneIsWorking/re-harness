#!/usr/bin/env python3
"""Run one heavy command under machine-wide admission (a slot, a memory reservation, a floor).

    heavy.py [--kind build|run] [--lock-dir DIR] [--mem-mib N] -- <command> [args...]

``build`` is a compiler or verifier run (a few at once, each with a moderate -j);
``run`` is one game, browser, Ghidra or bot instance. The exit status is the
command's. See skills/global/swarm/SKILL.md, "Slots, heavy gates, and memory".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if not sys.platform.startswith("linux"):
    sys.exit("heavy: refused: Linux-only (flock slots, /proc/meminfo floor)")

from swarmkit import config
from swarmkit.admission import MachineSlots
from swarmkit.console import emit
from swarmkit.heavy import HeavyAdmission, run_admitted
from swarmkit.lifetime import RunLifetime
from swarmkit.pressure import PressureWatcher
from swarmkit.procs import MIB
from swarmkit.reservations import ReservationLedger


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="heavy.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--kind", choices=sorted(config.HEAVY_SLOTS), default="build")
    parser.add_argument("--lock-dir", type=Path, default=None)
    parser.add_argument(
        "--mem-mib",
        type=int,
        default=None,
        help="peak this command may grow into (default: the kind's reservation)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("no command given (use: heavy.py [--kind K] -- <command> ...)")
    if args.mem_mib is not None and args.mem_mib < 1:
        parser.error("--mem-mib must be a positive whole number of MiB")
    return args


def main(argv: list[str]) -> int:
    args = parse(argv)
    settings = config.SwarmConfig(
        lock_dir=(args.lock_dir or config.default_lock_dir()).resolve()
    )
    count = config.HEAVY_SLOTS[args.kind]
    floor_mib = config.HEAVY_MEMORY_FLOOR_MIB
    reserve_mib = args.mem_mib or config.HEAVY_RESERVE_MIB[args.kind]
    memory = ReservationLedger(
        settings.lock_dir,
        floor_mib,
        on_wait=lambda free, held, ahead: emit(
            f"heavy: waiting behind {ahead} earlier request(s), MemAvailable "
            f"{free // MIB} MiB - reserved {held} MiB < {floor_mib} MiB"
        ),
    )
    pressure = PressureWatcher(
        config.PRESSURE_PAUSE_MIB,
        config.PRESSURE_RESUME_MIB,
        on_event=emit,
    )
    admission = HeavyAdmission(
        slots=MachineSlots(settings.heavy_slot_dir(args.kind), count),
        memory=memory,
        reserve_mib=reserve_mib,
        kind=args.kind,
        pressure=pressure,
    )
    pressure.start()
    try:
        return run_admitted(
            admission,
            args.command,
            RunLifetime(),
            on_wait=lambda: emit(f"heavy: all {count} {args.kind} slots busy; waiting"),
        )
    finally:
        pressure.stop()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
