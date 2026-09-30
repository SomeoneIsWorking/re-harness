#!/usr/bin/env python3
"""Check the machine for the failure modes that stall agent work; stop runaway processes.

    watchdog.py [--lock-dir DIR] [--kill] [--repo PATH ...] [--shared PATH ...]

Prints one line per alert and appends them, timestamped, to
``<lock-dir>/watchdog/alerts.log``. With ``--kill`` a runaway process (large,
still growing, not a Claude or desktop process)
is stopped by PID. ``--repo`` names a repo whose origin/main should keep
landing; ``--shared`` a checkout that must stay clean with its submodules at
their recorded commits. See skills/global/swarm/SKILL.md, "Watchdog".
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

if not sys.platform.startswith("linux"):
    sys.exit("watchdog: refused: Linux-only (/proc)")

from swarmkit import config
from swarmkit.procs import process_running
from swarmkit.watch import WatchState, run_checks
from swarmkit.watch_snapshot import take_snapshot

KILL_GRACE_SECONDS = 5.0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="watchdog.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--lock-dir", type=Path, default=None)
    parser.add_argument(
        "--kill", action="store_true", help="stop runaway processes by PID"
    )
    parser.add_argument("--repo", type=Path, action="append", default=[])
    parser.add_argument("--shared", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    lock_dir = (args.lock_dir or config.default_lock_dir()).resolve()
    home = lock_dir / "watchdog"
    state_path = home / "state.json"
    state = WatchState.load(state_path)
    alerts = run_checks(take_snapshot(args.repo, args.shared), state)
    state.save(state_path)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    for alert in alerts:
        line = alert.line()
        if args.kill and alert.kill_pid is not None:
            line += f" -> {_stop(alert.kill_pid)}"
        lines.append(line)
        print(line)
    if lines:
        with (home / "alerts.log").open("a", encoding="utf-8") as log:
            log.writelines(f"{stamp} {line}\n" for line in lines)
    return 0


def _stop(pid: int) -> str:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already gone"
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not process_running(pid):
            return "stopped (SIGTERM)"
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "stopped (SIGTERM)"
    return "killed (SIGKILL)"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
