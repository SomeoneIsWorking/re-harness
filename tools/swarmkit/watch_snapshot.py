"""Read one watchdog ``Snapshot`` from the live machine: /proc, git, pinest."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from .jobs import JobFileError, load_jobs
from .procs import MIB, PAGE_SIZE, PROC
from .results import RESULT_FILE
from .watch import Agent, Checkout, Process, Snapshot, SwarmRun
from .worktree import SWARM_SCRATCH

CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
GIT_TIMEOUT_SECONDS = 60
# /proc/<pid>/stat fields after comm: state(0) ppid(1) pgrp(2) ... starttime(19)
PPID, PGRP, START = 1, 2, 19


def take_snapshot(repos: Sequence[Path], shared: Sequence[Path]) -> Snapshot:
    now = time.time()
    processes = tuple(_processes(now))
    return Snapshot(
        now=now,
        processes=processes,
        swarms=tuple(_swarms(processes)),
        agents=tuple(_agents()),
        last_commit={str(repo): when for repo in repos if (when := _last_commit(repo))},
        checkouts=tuple(_checkout(path) for path in shared),
    )


def _processes(now: float) -> list[Process]:
    uptime = float((PROC / "uptime").read_text(encoding="ascii").split()[0])
    boot = now - uptime
    found = []
    for name in os.listdir(PROC):
        if not name.isdigit():
            continue
        entry = PROC / name
        try:
            fields = (entry / "stat").read_text(encoding="ascii", errors="replace")
            fields = fields.rsplit(")", 1)[-1].split()
            pages = int((entry / "statm").read_text(encoding="ascii").split()[1])
            command = (
                (entry / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", "replace")
                .strip()
            )
            cwd = os.readlink(entry / "cwd")
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
            continue
        started = boot + int(fields[START]) / CLOCK_TICKS
        found.append(
            Process(
                pid=int(name),
                ppid=int(fields[PPID]),
                group=int(fields[PGRP]),
                rss_mib=pages * PAGE_SIZE // MIB,
                age_seconds=now - started,
                cwd=cwd,
                command=command,
            )
        )
    return found


def _swarms(processes: Sequence[Process]) -> list[SwarmRun]:
    runs = []
    for process in processes:
        argv = process.command.split()
        if (
            "swarm.py" not in " ".join(argv[:3])
            or "run" not in argv
            or "--name" not in argv
        ):
            continue
        name = argv[argv.index("--name") + 1]
        jobs_path = next(
            (Path(process.cwd) / word for word in argv if word.endswith(".jsonl")), None
        )
        if jobs_path is None:
            continue
        try:
            jobs = load_jobs(jobs_path)
        except (JobFileError, FileNotFoundError):
            continue
        verdicts = 0
        for job in jobs:
            run_dir = job.repo / SWARM_SCRATCH / name
            verdicts += (run_dir / job.id / RESULT_FILE).is_file()
        runs.append(SwarmRun(name, process.pid, verdicts, len(jobs)))
    return runs


def _agents() -> list[Agent]:
    tool = shutil.which("pinest-agent")
    if tool is None:
        return []
    done = subprocess.run(
        [tool, "status"], capture_output=True, text=True, timeout=60, check=False
    )
    agents = []
    for line in done.stdout.splitlines():
        words = line.split()
        if len(words) >= 3 and words[1] in {"working", "idle", "error"}:
            agents.append(Agent(words[0], words[1], words[-1]))
    return agents


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )


def _last_commit(repo: Path) -> float | None:
    _git(repo, "fetch", "-q", "origin", "main")
    done = _git(repo, "log", "-1", "--format=%ct", "origin/main")
    return float(done.stdout) if done.returncode == 0 and done.stdout.strip() else None


def _checkout(path: Path) -> Checkout:
    problems = [
        f"modified {line[3:]}"
        for line in _git(
            path, "status", "--porcelain", "--untracked-files=no"
        ).stdout.splitlines()
    ]
    for line in _git(path, "submodule", "status").stdout.splitlines():
        if line[:1] in {"-", "+", "U"}:
            state = {
                "-": "uninitialised",
                "+": "off its recorded commit",
                "U": "conflicted",
            }
            problems.append(f"submodule {line[1:].split()[1]} {state[line[0]]}")
    return Checkout(str(path), tuple(problems))
