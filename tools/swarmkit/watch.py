"""The machine watchdog: detect the failure modes that stalled work, and stop runaways.

Each check reads one ``Snapshot`` of the machine plus the watchdog's own memory
of earlier runs (``WatchState``), and returns the alerts it found. Every check
here exists because its failure cost hours on 2026-09-30:

- ``runaway_memory``: a music render outside heavy.py grew to 10 GiB, and the
  low-memory reaper killed two swarm launchers. The watchdog kills such a
  process by PID (never by name) once it is large, still growing, and is not
  a Claude process.
- ``swarm_stall``: a batch ran 85 minutes without one verdict.
- ``idle_agent``: finished agents sat for an hour with nobody reviewing them.
- ``quiet_repo``: an active repo landed nothing for hours.
- ``damaged_checkout``: an agent's race emptied a shared checkout's submodule.
- ``detached_process``: agents detached builds with nohup, so the host never
  woke them when the build ended.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

RUNAWAY_MIB = 4096
RUNAWAY_GROWTH_MIB = 256
SWARM_STALL_SECONDS = 90 * 60
AGENT_IDLE_SECONDS = 15 * 60
QUIET_REPO_SECONDS = 90 * 60
DETACHED_GRACE_SECONDS = 60
# A process whose command line names one of these is never killed.
PROTECTED_WORDS = ("claude", "pinest", "systemd", "gnome", "plasma", "Xwayland")


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    group: int
    rss_mib: int
    age_seconds: float
    cwd: str
    command: str


@dataclass(frozen=True)
class SwarmRun:
    name: str
    launcher_pid: int
    verdicts: int
    jobs: int


@dataclass(frozen=True)
class Agent:
    name: str
    status: str
    cwd: str


@dataclass(frozen=True)
class Checkout:
    path: str
    # Lines from `git status --porcelain` and `git submodule status` that show damage.
    problems: tuple[str, ...]


@dataclass(frozen=True)
class Snapshot:
    now: float
    processes: tuple[Process, ...] = ()
    swarms: tuple[SwarmRun, ...] = ()
    agents: tuple[Agent, ...] = ()
    last_commit: dict[str, float] = field(default_factory=dict)
    checkouts: tuple[Checkout, ...] = ()


@dataclass(frozen=True)
class Alert:
    kind: str
    subject: str
    message: str
    kill_pid: int | None = None

    def line(self) -> str:
        return f"{self.kind} {self.subject}: {self.message}"


@dataclass
class WatchState:
    """What the watchdog remembers between runs, so a condition can be timed."""

    rss_mib: dict[str, int] = field(default_factory=dict)
    swarm_progress: dict[str, list[float]] = field(default_factory=dict)
    idle_since: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> WatchState:
        try:
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.__dict__, indent=1) + "\n", encoding="utf-8"
        )
        temporary.replace(path)


Check = Callable[[Snapshot, WatchState], list[Alert]]


def runaway_memory(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    alerts = []
    seen = {}
    for process in snapshot.processes:
        seen[str(process.pid)] = process.rss_mib
        if process.rss_mib < RUNAWAY_MIB:
            continue
        if any(word in process.command for word in PROTECTED_WORDS):
            continue
        before = state.rss_mib.get(str(process.pid))
        if before is None or process.rss_mib - before < RUNAWAY_GROWTH_MIB:
            continue
        alerts.append(
            Alert(
                "runaway_memory",
                f"pid {process.pid}",
                f"{before} -> {process.rss_mib} MiB: "
                f"{process.command[:120]} (cwd {process.cwd})",
                kill_pid=process.pid,
            )
        )
    state.rss_mib = seen
    return alerts


def swarm_stall(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    alerts = []
    progress = {}
    for run in snapshot.swarms:
        key = f"{run.name}:{run.launcher_pid}"
        verdicts, since = state.swarm_progress.get(key, [run.verdicts, snapshot.now])
        if run.verdicts != verdicts:
            verdicts, since = run.verdicts, snapshot.now
        progress[key] = [verdicts, since]
        if snapshot.now - since > SWARM_STALL_SECONDS and run.verdicts < run.jobs:
            alerts.append(
                Alert(
                    "swarm_stall",
                    run.name,
                    f"no new verdict for {(snapshot.now - since) / 60:.0f} min "
                    f"({run.verdicts}/{run.jobs})",
                )
            )
    state.swarm_progress = progress
    return alerts


def idle_agent(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    alerts = []
    idle = {}
    for agent in snapshot.agents:
        if agent.status == "working":
            continue
        since = state.idle_since.get(agent.name, snapshot.now)
        idle[agent.name] = since
        if snapshot.now - since > AGENT_IDLE_SECONDS:
            alerts.append(
                Alert(
                    "idle_agent",
                    agent.name,
                    f"{agent.status} for {(snapshot.now - since) / 60:.0f} min in {agent.cwd}",
                )
            )
    state.idle_since = idle
    return alerts


def quiet_repo(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    return [
        Alert(
            "quiet_repo",
            repo,
            f"nothing landed for {(snapshot.now - when) / 60:.0f} min",
        )
        for repo, when in snapshot.last_commit.items()
        if snapshot.now - when > QUIET_REPO_SECONDS
    ]


def damaged_checkout(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    return [
        Alert("damaged_checkout", checkout.path, "; ".join(checkout.problems[:5]))
        for checkout in snapshot.checkouts
        if checkout.problems
    ]


def detached_process(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    return [
        Alert(
            "detached_process",
            f"pid {process.pid}",
            f"detached from its agent (parent is init) in {process.cwd}: {process.command[:100]}",
        )
        for process in snapshot.processes
        if process.ppid == 1
        and "/scratch/wt/" in process.cwd
        and process.age_seconds > DETACHED_GRACE_SECONDS
    ]


CHECKS: Sequence[Check] = (
    runaway_memory,
    swarm_stall,
    idle_agent,
    quiet_repo,
    damaged_checkout,
    detached_process,
)


def run_checks(snapshot: Snapshot, state: WatchState) -> list[Alert]:
    alerts: list[Alert] = []
    for check in CHECKS:
        alerts.extend(check(snapshot, state))
    return alerts
