#!/usr/bin/env python3
"""Run one heavy command at once, as a unit the pressure guard can pause under real memory pressure.

    heavy.py [--kind build|run] [--lock-dir DIR] -- <command> [args...]

``build`` is a compiler or verifier run; ``run`` is one game, browser, Ghidra or
bot instance. Nothing is queued: the command starts immediately, runs under the
reaper so its whole subtree ends with it, and is registered so that
``pressure_guard.py`` can pause it if the host runs out of memory. The exit
status is the command's. See skills/global/swarm/SKILL.md, "Memory".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if not sys.platform.startswith("linux"):
    sys.exit("heavy: refused: Linux-only (process groups, subreaper)")

from swarmkit import config
from swarmkit.heavy import run_unit
from swarmkit.lifetime import RunLifetime
from swarmkit.units import UnitRegistry


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="heavy.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--kind", choices=("build", "run"), default="build")
    parser.add_argument("--lock-dir", type=Path, default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("no command given (use: heavy.py [--kind K] -- <command> ...)")
    return args


def main(argv: list[str]) -> int:
    args = parse(argv)
    lock_dir = (args.lock_dir or config.default_lock_dir()).resolve()
    return run_unit(UnitRegistry(lock_dir), args.kind, args.command, RunLifetime())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
