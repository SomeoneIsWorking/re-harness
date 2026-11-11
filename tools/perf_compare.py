#!/usr/bin/env python3
"""Compare the run-end cost lines of two builds, each side with optional repeat runs.

A cost line is ``[<tag>] <name>: p50 <a> p99 <b> max <c> <unit>/<per>, total <t> <unit>``
(the ``perf-units`` skill); ``[<tag>] <name> run-end: ...`` lines are the header of each group and
must agree between runs. Each side's spread, (max - min) / mean over its runs, is its noise floor;
a delta inside the larger spread is noise.

    uv run --no-project python tools/perf_compare.py A1.log A2.log --vs B1.log B2.log
    uv run --no-project python tools/perf_compare.py A1.log A2.log        # one build: its spread
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FIELDS = ("p50", "p99", "max", "total")
SAME = 1e-9  # relative: equal printed figures averaged in floating point


@dataclass(frozen=True)
class CostLine:
    name: str
    unit: str  # of a total
    per: str  # a percentile's denominator
    values: dict[str, float]

    def unit_of(self, field: str) -> str:
        return self.unit if field == "total" else f"{self.unit}/{self.per}"


@dataclass(frozen=True)
class RunLog:
    path: Path
    costs: dict[str, CostLine]
    headers: dict[str, str]


def line_pattern(tag: str) -> re.Pattern[str]:
    return re.compile(
        r"\[" + re.escape(tag) + r"\] (?P<name>[^:]+): p50 (?P<p50>[\d.]+) p99 (?P<p99>[\d.]+) "
        r"max (?P<max>[\d.]+) (?P<unit>\S+)/(?P<per>\S+), total (?P<total>[\d.]+) \S+"
    )


def header_pattern(tag: str) -> re.Pattern[str]:
    return re.compile(r"\[" + re.escape(tag) + r"\] (?P<name>[^:]+ run-end): (?P<text>.*)$")


def read_log(path: Path, tag: str) -> RunLog:
    cost_re, header_re = line_pattern(tag), header_pattern(tag)
    costs: dict[str, CostLine] = {}
    headers: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if match := header_re.search(line):
            headers[match["name"]] = match["text"].strip()
        elif match := cost_re.search(line):
            costs[match["name"]] = CostLine(
                match["name"],
                match["unit"],
                match["per"],
                {field: float(match[field]) for field in FIELDS},
            )
    if not costs:
        raise ValueError(f"{path}: no [{tag}] cost lines (did the run reach its end report?)")
    return RunLog(path, costs, headers)


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def spread_pct(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    centre = mean(values)
    return 0.0 if centre == 0 else (max(values) - min(values)) / abs(centre) * 100.0


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}%"


def header_mismatches(runs: list[RunLog]) -> list[str]:
    names = sorted({name for run in runs for name in run.headers})
    problems = []
    for name in names:
        texts = {run.headers.get(name, "<missing>") for run in runs}
        if len(texts) > 1:
            problems.append(f"{name} differs between runs: " + " | ".join(sorted(texts)))
    return problems


def side_values(runs: list[RunLog], name: str, field: str) -> list[float]:
    return [run.costs[name].values[field] for run in runs if name in run.costs]


def report(base: list[RunLog], other: list[RunLog], field: str) -> int:
    runs = base + other
    for problem in header_mismatches(runs):
        print(f"WARNING {problem}")
    names = list(dict.fromkeys(name for run in runs for name in run.costs))
    width = max(len(name) for name in names)
    if other:
        print(f"{'line':{width}}  {'unit':14} {'A ' + field:>14} {'B ' + field:>14} "
              f"{'delta':>9}  spread A  spread B  verdict")
    else:
        print(f"{'line':{width}}  {'unit':14} {'mean ' + field:>14} {'min':>14} {'max':>14}  spread")
    changed = 0
    for name in names:
        unit = next(run.costs[name].unit_of(field) for run in runs if name in run.costs)
        a = side_values(base, name, field)
        if not other:
            if a:
                print(f"{name:{width}}  {unit:14} {mean(a):14.3f} {min(a):14.3f} {max(a):14.3f}  "
                      f"{fmt_pct(spread_pct(a))}")
            continue
        b = side_values(other, name, field)
        if not a or not b:
            print(f"{name:{width}}  {unit:14} missing on side {'A' if not a else 'B'}")
            changed += 1
            continue
        ma, mb = mean(a), mean(b)
        delta = 0.0 if abs(mb - ma) <= SAME * max(abs(ma), abs(mb)) else (
            (mb - ma) / abs(ma) * 100.0 if ma else float("inf"))
        floors = [s for s in (spread_pct(a), spread_pct(b)) if s is not None]
        if not floors:
            verdict = "no spread (one run per side)"
        elif abs(delta) <= max(floors):
            verdict = "noise"
        else:
            verdict = "CHANGED"
            changed += 1
        print(f"{name:{width}}  {unit:14} {ma:14.3f} {mb:14.3f} {delta:+8.3f}%  "
              f"{fmt_pct(spread_pct(a)):>8}  {fmt_pct(spread_pct(b)):>8}  {verdict}")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="+", type=Path, help="side A run logs (repeat runs of one build)")
    parser.add_argument("--vs", nargs="+", type=Path, default=[], help="side B run logs")
    parser.add_argument("--tag", default="perf", help="the bracketed log tag of the cost lines")
    parser.add_argument("--field", choices=FIELDS, default="total", help="the figure compared")
    args = parser.parse_args(argv)
    try:
        base = [read_log(path, args.tag) for path in args.base]
        other = [read_log(path, args.tag) for path in args.vs]
    except (OSError, ValueError) as error:
        print(f"perf_compare: {error}", file=sys.stderr)
        return 2
    print(f"A: {', '.join(str(run.path) for run in base)}")
    if other:
        print(f"B: {', '.join(str(run.path) for run in other)}")
    changed = report(base, other, args.field)
    if other:
        print(f"{changed} line(s) changed beyond the run-to-run spread")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
