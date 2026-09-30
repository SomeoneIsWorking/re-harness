"""Every watchdog check fires on the failure it exists for, and stays quiet otherwise."""

from __future__ import annotations

from collections.abc import Callable

from swarmkit.watch import (
    AGENT_IDLE_SECONDS,
    QUIET_REPO_SECONDS,
    SWARM_STALL_SECONDS,
    Agent,
    Checkout,
    Process,
    Snapshot,
    SwarmRun,
    WatchState,
    run_checks,
)

Check = Callable[..., int]


def process(pid: int, rss: int, command: str = "render music", **extra) -> Process:
    return Process(
        pid=pid,
        ppid=extra.get("ppid", 100),
        group=extra.get("group", pid),
        rss_mib=rss,
        age_seconds=extra.get("age", 600.0),
        cwd=extra.get("cwd", "/w"),
        command=command,
    )


def kinds(snapshot: Snapshot, state: WatchState) -> list[str]:
    return [alert.kind for alert in run_checks(snapshot, state)]


def run_checks_suite(check: Check) -> int:
    fails = 0
    state = WatchState()
    kinds(
        Snapshot(
            0,
            processes=(
                process(1, 5000),
                process(3, 5000, "claude --x"),
                process(4, 5000),
            ),
        ),
        state,
    )
    grown = Snapshot(
        60,
        processes=(
            process(1, 6000),
            process(3, 6000, "claude --x"),
            process(4, 5100),
        ),
    )
    alerts = [a for a in run_checks(grown, state) if a.kind == "runaway_memory"]
    fails += check(
        "watch: a growing process outside any unit is a runaway to stop by PID",
        [a.kill_pid for a in alerts] == [1],
        str(alerts),
    )
    fails += check(
        "watch: NEGATIVE a Claude or a barely growing process is left alone",
        all(a.kill_pid == 1 for a in alerts),
    )
    fails += check(
        "watch: NEGATIVE a large process seen for the first time is not killed",
        "runaway_memory"
        not in kinds(Snapshot(0, processes=(process(7, 9000),)), WatchState()),
    )

    state = WatchState()
    run = SwarmRun("b", 11, 3, 10)
    kinds(Snapshot(0, swarms=(run,)), state)
    fails += check(
        "watch: a swarm with no new verdict for too long is stalled",
        "swarm_stall" in kinds(Snapshot(SWARM_STALL_SECONDS + 1, swarms=(run,)), state),
    )
    state = WatchState()
    kinds(Snapshot(0, swarms=(run,)), state)
    moved = SwarmRun("b", 11, 4, 10)
    fails += check(
        "watch: NEGATIVE a new verdict resets the stall clock",
        "swarm_stall"
        not in kinds(Snapshot(SWARM_STALL_SECONDS + 1, swarms=(moved,)), state),
    )

    state = WatchState()
    idle = Agent("a", "idle", "/wt")
    kinds(Snapshot(0, agents=(idle,)), state)
    fails += check(
        "watch: an agent idle too long is reported",
        "idle_agent" in kinds(Snapshot(AGENT_IDLE_SECONDS + 1, agents=(idle,)), state),
    )
    state = WatchState()
    kinds(Snapshot(0, agents=(idle,)), state)
    kinds(Snapshot(10, agents=(Agent("a", "working", "/wt"),)), state)
    fails += check(
        "watch: NEGATIVE working again resets an agent's idle clock",
        "idle_agent"
        not in kinds(Snapshot(AGENT_IDLE_SECONDS + 1, agents=(idle,)), state),
    )

    fails += check(
        "watch: a repo that landed nothing for too long is quiet",
        kinds(Snapshot(QUIET_REPO_SECONDS + 1, last_commit={"r": 0}), WatchState())
        == ["quiet_repo"],
    )
    fails += check(
        "watch: NEGATIVE a repo that landed recently is not",
        not kinds(Snapshot(60, last_commit={"r": 0}), WatchState()),
    )

    damaged = Checkout("/p", ("submodule vendor/beetle-psx uninitialised",))
    fails += check(
        "watch: a damaged shared checkout is reported",
        kinds(Snapshot(0, checkouts=(damaged,)), WatchState()) == ["damaged_checkout"],
    )
    fails += check(
        "watch: NEGATIVE a clean checkout is not",
        not kinds(Snapshot(0, checkouts=(Checkout("/p", ()),)), WatchState()),
    )

    detached = process(8, 100, "cmake --build", ppid=1, cwd="/r/scratch/wt/x", age=120)
    fails += check(
        "watch: a build an agent detached to init is reported",
        kinds(Snapshot(0, processes=(detached,)), WatchState()) == ["detached_process"],
    )
    attached = process(8, 100, "cmake --build", ppid=50, cwd="/r/scratch/wt/x", age=120)
    fails += check(
        "watch: NEGATIVE a build with its agent as parent is not",
        not kinds(Snapshot(0, processes=(attached,)), WatchState()),
    )
    return fails
