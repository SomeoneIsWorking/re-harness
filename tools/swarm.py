#!/usr/bin/env python3
"""Fan bounded jobs out to a free LLM worker and accept results only through a scripted gate.

Each job runs in a detached git worktree under ``<repo>/scratch/swarm/<run>/<id>/tree``.
After the worker exits, its changes are captured as ``patch.diff`` and the job's gate
argv runs in the worktree; exit 0 is the only way a job becomes ``accepted``. Nothing is
ever committed; ``apply`` copies an accepted patch into the main working tree.

    swarm.py run jobs.jsonl [--backend opencode|pi] [--workers 8] [--retries 0]
    swarm.py report <run-dir>
    swarm.py apply <run-dir> <job-id>
    swarm.py gc <run-dir>

See skills/global/swarm/SKILL.md for the jobs format and the slot/lock rules.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

SUPPORTED = sys.platform.startswith("linux")
if not SUPPORTED:
    sys.exit(
        "swarm: refused: Linux-only (flock(1) heavy lock, /proc/meminfo floor, "
        "POSIX process groups)"
    )

from swarmkit import config
from swarmkit.admission import MIB, MachineSlots, MemoryFloor
from swarmkit.apply import ApplyRefused, apply_accepted
from swarmkit.backends import BACKENDS, DEFAULT_BACKEND
from swarmkit.cleanup import CleanupRefused, remove_worktrees
from swarmkit.console import emit
from swarmkit.jobs import JOB_ID, JobFileError, load_jobs
from swarmkit.lifetime import RunInterrupted, RunLifetime
from swarmkit.report import summarize
from swarmkit.results import Verdict
from swarmkit.runner import RunSettings, run_jobs
from swarmkit.worktree import WorktreeError


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except (KeyboardInterrupt, RunInterrupted):
        emit("swarm: interrupted; in-flight jobs were stopped and have no verdict")
        return 130
    except (
        JobFileError,
        WorktreeError,
        ApplyRefused,
        CleanupRefused,
        FileExistsError,
        FileNotFoundError,
    ) as error:
        emit(f"swarm: refused: {error}")
        return 2


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a JSONL jobs file")
    run.add_argument("jobs", type=Path)
    run.add_argument("--backend", choices=sorted(BACKENDS), default=DEFAULT_BACKEND)
    run.add_argument("--model", default=config.DEFAULT_MODEL)
    run.add_argument("--workers", type=positive, default=config.DEFAULT_WORKERS)
    run.add_argument(
        "--retries",
        type=int,
        default=0,
        help="re-prompt a rejected worker up to N times with the gate output",
    )
    run.add_argument("--name", help="run name (default: UTC timestamp)")
    run.add_argument(
        "--lock-dir",
        type=Path,
        default=None,
        help=f"shared lock root (default: ${config.LOCK_DIR_VARIABLE} "
        "or ~/repo/scratch/locks)",
    )
    run.add_argument(
        "--heavy-lock",
        type=Path,
        default=None,
        help="flock file for heavy gates (default: <lock-dir>/heavy.lock)",
    )
    run.add_argument(
        "--slots",
        type=positive,
        default=config.DEFAULT_SLOTS,
        help="machine-wide worker cap shared by every swarm invocation",
    )
    run.add_argument(
        "--mem-floor-mib",
        type=int,
        default=config.DEFAULT_MEMORY_FLOOR_MIB,
        help="do not start a worker while MemAvailable is below this",
    )
    run.set_defaults(handler=command_run)

    report = commands.add_parser("report", help="print a run's denominators")
    report.add_argument("run_dir", type=Path)
    report.set_defaults(handler=command_report)

    apply = commands.add_parser(
        "apply", help="apply an accepted patch to the main tree"
    )
    apply.add_argument("run_dir", type=Path)
    apply.add_argument("job_id")
    apply.set_defaults(handler=command_apply)

    gc = commands.add_parser("gc", help="remove a run's worktrees (keeps results)")
    gc.add_argument("run_dir", type=Path)
    gc.set_defaults(handler=command_gc)
    return top


def positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def command_run(args: argparse.Namespace) -> int:
    jobs = load_jobs(args.jobs)
    name = args.name or time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    if not JOB_ID.match(name):
        raise JobFileError(f"run name {name!r} must match {JOB_ID.pattern}")
    settings_config = config.SwarmConfig(
        lock_dir=(args.lock_dir or config.default_lock_dir()).resolve(),
        slots=args.slots,
        memory_floor_mib=args.mem_floor_mib,
    )
    memory = MemoryFloor(
        settings_config.memory_floor_mib * MIB,
        on_wait=lambda free: emit(
            f"swarm: waiting, MemAvailable {free // MIB} MiB "
            f"< floor {settings_config.memory_floor_mib} MiB"
        ),
    )
    settings = RunSettings(
        backend=BACKENDS[args.backend],
        model=args.model,
        retries=args.retries,
        heavy_lock=(args.heavy_lock or settings_config.heavy_lock).resolve(),
        slots=MachineSlots(settings_config.slot_dir, settings_config.slots),
        memory=memory,
        lifetime=RunLifetime(),
    )
    signal.signal(signal.SIGTERM, interrupt)
    results = run_jobs(jobs, name, settings, args.workers)
    accepted = sum(result.verdict is Verdict.ACCEPTED for result in results)
    emit(f"swarm: {accepted}/{len(results)} accepted")
    return 0


def interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def command_report(args: argparse.Namespace) -> int:
    for line in summarize(args.run_dir):
        print(line)
    return 0


def command_apply(args: argparse.Namespace) -> int:
    result = apply_accepted(args.run_dir, args.job_id)
    emit(
        f"swarm: applied {args.job_id} ({len(result.changed_files)} file(s)) to {result.repo}"
    )
    return 0


def command_gc(args: argparse.Namespace) -> int:
    remove_worktrees(args.run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
