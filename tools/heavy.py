#!/usr/bin/env python3
"""Run a heavy job when the machine has room for it, instead of one heavy job at a time.

A heavy job (a build, a lint pass, a check suite, a bot sweep, an emulator, a container) states the
cores and memory it needs. It starts once the machine has that much to spare:

* cores: the machine's cores, less the larger of the 1-minute load and the cores already reserved by
  running jobs (load average lags, so a job that just started still counts by its reservation);
* memory: MemAvailable, less the memory of jobs started in the last two minutes (they have not grown
  yet), less a reserve for the desktop.

A job alone on the machine waits only for memory. Each running job holds a locked reservation file
under ~/agents/heavy/ naming its pid, command and request; a job that dies frees its share with it.
The runner watches its job's process tree and records since when it has used no CPU, so a hung job
shows in `status` and in the lines a waiting job prints. A job that runs podman or distrobox is shown
as in a container instead: the container's processes run under conmon, outside the job's tree, where its
CPU can't be seen. Linux only (it reads /proc).

  heavy.py run --cores 4 --memory 6 -- cmake --build build/agent
  heavy.py run --cores 8 --memory 12 --label psx-scan -- uv run --frozen python tools/scan.py
  heavy.py status
  heavy.py free          # what a new job could have right now

`run` exits with the job's exit code. `--label` names the job in status lines (default: the command).
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

LEDGER = Path.home() / "agents" / "heavy"
ADMIT_LOCK = LEDGER / ".admit"
POLL_SECONDS = 5
REPORT_SECONDS = 60
RAMP_SECONDS = 120
WATCH_SECONDS = 60
GIB = 1 << 30
PR_SET_PDEATHSIG = 1


def total_cores() -> int:
    return os.cpu_count() or 1


def meminfo() -> dict[str, int]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, rest = line.split(":", 1)
        values[name] = int(rest.split()[0]) * 1024
    return values


def desktop_reserve(total: int) -> int:
    """Memory kept back for the desktop and everything not run through heavy.py."""
    return max(int(1.5 * GIB), total // 10)


class Reservation:
    """One running job's claim, held by flock on its file for as long as the runner lives."""

    def __init__(self, path: Path, data: dict) -> None:
        self.path = path
        self.data = data

    @property
    def cores(self) -> float:
        return float(self.data["cores"])

    @property
    def memory(self) -> int:
        return int(float(self.data["memory_gib"]) * GIB)

    @property
    def age(self) -> float:
        return time.time() - float(self.data["started"])

    def describe(self) -> str:
        idle = self.data.get("idle_since")
        hung = f", no CPU for {duration(time.time() - idle)}" if idle else ""
        if self.data.get("container"):
            hung = ", in a container (its CPU isn't visible)"
        return (f"{self.data['label']} (pid {self.data['pid']}, {self.data['cores']} cores, "
                f"{self.data['memory_gib']} GiB, running {duration(self.age)}{hung})")


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def live_reservations() -> list[Reservation]:
    """Reservations whose runner still holds them; files left by dead runners are removed."""
    found = []
    for path in sorted(LEDGER.glob("*.json")):
        try:
            with open(path) as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    found.append(Reservation(path, json.loads(path.read_text())))
                    continue
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
        except json.JSONDecodeError:
            # Caught mid-rewrite: count it on the next poll.
            continue
    return found


class Room:
    """What the machine can give a new job now."""

    def __init__(self, running: list[Reservation]) -> None:
        info = meminfo()
        self.running = running
        self.cores_total = total_cores()
        self.load = os.getloadavg()[0]
        reserved = sum(r.cores for r in running)
        self.cores = self.cores_total - max(self.load, reserved)
        ramping = sum(r.memory for r in running if r.age < RAMP_SECONDS)
        self.reserve = desktop_reserve(info["MemTotal"])
        self.memory = info["MemAvailable"] - ramping - self.reserve

    def admits(self, cores: float, memory: int) -> tuple[bool, str]:
        if self.memory < memory:
            return False, f"memory: {self.memory / GIB:.1f} GiB spare of {memory / GIB:.1f} GiB asked"
        if self.running and self.cores < cores:
            return False, f"cores: {max(self.cores, 0):.1f} spare of {cores:g} asked (load {self.load:.1f})"
        return True, ""

    def summary(self) -> str:
        return (f"{max(self.cores, 0):.1f} of {self.cores_total} cores spare (load {self.load:.1f}), "
                f"{max(self.memory, 0) / GIB:.1f} GiB memory spare after a {self.reserve / GIB:.1f} GiB desktop reserve")


CONTAINER_COMMANDS = {"podman", "distrobox", "distrobox-enter", "docker"}


def process_tree_cpu(root: int) -> tuple[int, bool]:
    """CPU ticks used so far by root and every process under it, and whether one of them starts a container."""
    children: dict[int, list[int]] = {}
    ticks: dict[int, int] = {}
    names: dict[int, str] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        fields = stat[stat.rindex(")") + 2:].split()
        pid = int(entry.name)
        names[pid] = stat[stat.index("(") + 1:stat.rindex(")")]
        children.setdefault(int(fields[1]), []).append(pid)
        ticks[pid] = int(fields[11]) + int(fields[12]) + int(fields[13]) + int(fields[14])
    total, container, stack = 0, False, [root]
    while stack:
        pid = stack.pop()
        total += ticks.get(pid, 0)
        container |= names.get(pid) in CONTAINER_COMMANDS
        stack.extend(children.get(pid, []))
    return total, container


def reserve(cores: float, memory_gib: float, label: str) -> tuple:
    """Waits for room, then returns the open, locked reservation file and its data."""
    LEDGER.mkdir(parents=True, exist_ok=True)
    memory = int(memory_gib * GIB)
    if memory > meminfo()["MemTotal"] - desktop_reserve(meminfo()["MemTotal"]):
        sys.exit(f"heavy.py: {memory_gib} GiB is more than this machine can ever spare")
    waited_since = time.monotonic()
    reported = 0.0
    while True:
        with open(ADMIT_LOCK, "a") as admit:
            fcntl.flock(admit, fcntl.LOCK_EX)
            running = live_reservations()
            room = Room(running)
            fits, why = room.admits(cores, memory)
            if fits:
                data = {"pid": os.getpid(), "label": label, "cores": cores, "memory_gib": memory_gib,
                        "started": time.time(), "cwd": os.getcwd()}
                path = LEDGER / f"{os.getpid()}-{int(time.time())}.json"
                handle = open(path, "w")
                fcntl.flock(handle, fcntl.LOCK_EX)
                handle.write(json.dumps(data))
                handle.flush()
                return path, handle, data
        waited = time.monotonic() - waited_since
        if waited - reported >= REPORT_SECONDS or reported == 0.0:
            reported = max(waited, 1e-9)
            holders = "; ".join(r.describe() for r in running) or "nothing reserved, the load is from outside"
            print(f"heavy.py: {label} waits for {why}; running: {holders}", file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)


def watch(child: subprocess.Popen, handle, data: dict, stop: threading.Event) -> None:
    """Records in the reservation since when the job's process tree has used no CPU."""
    last, _ = process_tree_cpu(child.pid)
    while not stop.wait(WATCH_SECONDS):
        now, container = process_tree_cpu(child.pid)
        if container:
            data["container"] = True
        if now > last:
            data.pop("idle_since", None)
        else:
            data.setdefault("idle_since", time.time() - WATCH_SECONDS)
        last = now
        # Rewritten in place: a new file would not carry the held lock.
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(data))
        handle.flush()


def die_with_runner() -> None:
    """The job gets SIGKILL if its runner dies, so a reservation is never freed under a live job."""
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL)


def run(args: argparse.Namespace) -> int:
    if not args.command:
        sys.exit("heavy.py run: give the command after --")
    label = args.label or shlex.join(args.command)[:120]
    path, handle, data = reserve(args.cores, args.memory, label)
    child = subprocess.Popen(args.command, start_new_session=True, preexec_fn=die_with_runner)
    data["child"] = child.pid

    def forward(signum, _frame):
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, forward)
    stop = threading.Event()
    watcher = threading.Thread(target=watch, args=(child, handle, data, stop), daemon=True)
    watcher.start()
    try:
        return child.wait()
    finally:
        stop.set()
        watcher.join()
        path.unlink(missing_ok=True)
        handle.close()


def status(_args: argparse.Namespace) -> int:
    LEDGER.mkdir(parents=True, exist_ok=True)
    running = live_reservations()
    for r in running:
        print(r.describe())
    if not running:
        print("no heavy jobs running")
    print(Room(running).summary())
    return 0


def free(_args: argparse.Namespace) -> int:
    LEDGER.mkdir(parents=True, exist_ok=True)
    print(Room(live_reservations()).summary())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    runner = commands.add_parser("run", help="wait for room, then run the command holding a reservation")
    runner.add_argument("--cores", type=float, required=True, help="cores the job keeps busy")
    runner.add_argument("--memory", type=float, required=True, help="GiB of memory the job grows to")
    runner.add_argument("--label", help="the job's name in status lines (default: the command)")
    runner.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command")
    commands.add_parser("status", help="running jobs, hung ones flagged, and the spare room")
    commands.add_parser("free", help="the spare room a new job could have")
    args = parser.parse_args(argv)
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]
    return {"run": run, "status": status, "free": free}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
