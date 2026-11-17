#!/usr/bin/env python3
"""Run any command N times under Linux perf and write its cost as standard run-end lines.

For a program with no meter of its own (the ``perf-units`` skill): each run's user-space instructions
retired, the whole process exactly through ``perf stat``, or with ``--threads`` per thread name through
``perf record`` (each thread within one sample period). Each run's lines go to ``<out>/run<i>.log`` in
the ``[perf]`` format ``perf_compare.py`` reads, and the spread over the runs is printed.

    uv run --no-project python tools/perf_run.py -n 3 --name bench -- ./build/agent/bench --frames 600
    uv run --no-project python tools/perf_compare.py scratch/perf-run/bench/run*.log --vs other/run*.log
"""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import perf_compare

EVENT = "instructions:u"


def stat_total(command: list[str], work: Path) -> int:
    out = work / "stat.csv"
    run(["perf", "stat", "-x,", "-e", EVENT, "-o", str(out), "--", *command])
    for line in out.read_text().splitlines():
        fields = line.split(",")
        if len(fields) > 2 and fields[2].startswith("instructions"):
            if not fields[0].isdigit():
                raise SystemExit(f"perf_run: perf counted no instructions ({fields[0]}); "
                                 "kernel.perf_event_paranoid must be 2 or lower")
            return int(fields[0])
    raise SystemExit(f"perf_run: no instruction count in {out}")


def thread_totals(command: list[str], work: Path, period: int) -> dict[str, int]:
    data = work / "perf.data"
    run(["perf", "record", "-q", "-o", str(data), "-e", EVENT, "-c", str(period), "--", *command])
    report = subprocess.run(
        ["perf", "report", "-i", str(data), "--stdio", "--sort", "comm", "-F", "sample,comm"],
        check=True, capture_output=True, text=True).stdout
    data.unlink()
    threads: dict[str, int] = {}
    for line in report.splitlines():
        if match := re.match(r"\s*(\d+)\s+(.+?)\s*$", line):
            name = match[2].replace(":", ".")
            threads[name] = threads.get(name, 0) + int(match[1]) * period
    if not threads:
        raise SystemExit("perf_run: perf record took no samples")
    return threads


def run(command: list[str]) -> None:
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f"perf_run: {shlex.join(command)} exited {result.returncode}")


def cost_line(name: str, value: int) -> str:
    return f"[perf] {name}: p50 {value} p99 {value} max {value} insn/run, total {value} insn"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--runs", type=int, default=2, help="repeat runs (at least 2 for a spread)")
    parser.add_argument("--name", default="run", help="the lines' name and the output folder's")
    parser.add_argument("--out", type=Path, help="log folder (default scratch/perf-run/<name>)")
    parser.add_argument("--threads", action="store_true", help="per thread name, through perf record")
    parser.add_argument("--period", type=int, default=1000003, help="perf record's sample period")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- the command and its arguments")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command after --")
    if shutil.which("perf") is None:
        print("perf_run: perf is missing; Fedora: sudo dnf install perf, Debian/Ubuntu: "
              "sudo apt install linux-perf (or linux-tools-$(uname -r))", file=sys.stderr)
        return 2
    out = args.out or Path("scratch/perf-run") / args.name
    out.mkdir(parents=True, exist_ok=True)
    source = (f"per thread by perf record, each within {args.period} insn" if args.threads
              else "whole process by perf stat")
    logs = []
    for index in range(1, args.runs + 1):
        if args.threads:
            costs = {f"{args.name} thread {name}": value
                     for name, value in sorted(thread_totals(command, out, args.period).items())}
            costs[f"{args.name} process"] = sum(costs.values())
        else:
            costs = {f"{args.name} process": stat_total(command, out)}
        log = out / f"run{index}.log"
        log.write_text("\n".join(
            [f"[perf] {args.name} run-end: user instructions retired, {source}, {shlex.join(command)}"]
            + [cost_line(name, value) for name, value in costs.items()]) + "\n")
        print(f"run {index}: {log}")
        logs.append(log)
    perf_compare.report([perf_compare.read_log(log, "perf") for log in logs], [], "total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
