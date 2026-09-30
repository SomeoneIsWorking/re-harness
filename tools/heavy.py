#!/usr/bin/env python3
"""Run one heavy command at once, so its whole subtree ends with it.

    heavy.py -- <command> [args...]

A build, verifier, game, browser, Ghidra or bot run goes through here so that
nothing it starts outlives it (the reaper), and so a build in a worktree shares
ccache with its checkout. Nothing is queued, reserved or paused. The exit status
is the command's. See skills/global/swarm/SKILL.md.
"""

from __future__ import annotations

import argparse
import sys

if not sys.platform.startswith("linux"):
    sys.exit("heavy: refused: Linux-only (process groups, subreaper)")

from swarmkit.heavy import run_command
from swarmkit.lifetime import RunLifetime

# Removed on 2026-09-30 with admission and the pressure guard; name them in the refusal.
REMOVED_FLAGS = ("--kind", "--lock-dir", "--mem-mib")


def parse(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(
        prog="heavy.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    removed = [word for word in argv if word.split("=", 1)[0] in REMOVED_FLAGS]
    if removed and argv.index(removed[0]) < (
        argv.index("--") if "--" in argv else len(argv)
    ):
        parser.error(f"{removed[0]} was removed; run: heavy.py -- <command> ...")
    command = parser.parse_args(argv).command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("no command given (use: heavy.py -- <command> ...)")
    return command


def main(argv: list[str]) -> int:
    return run_command(parse(argv), RunLifetime())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
