"""Denominators for one run directory."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .results import RESULT_FILE, RUN_FILE, JobResult, Verdict


def summarize(run_dir: Path) -> list[str]:
    """Report lines for ``run_dir``; a listed job without a result counts as unfinished."""
    run_file = run_dir / RUN_FILE
    if not run_file.is_file():
        raise FileNotFoundError(
            f"{run_file} not found; is {run_dir} a swarm run directory?"
        )
    run = json.loads(run_file.read_text(encoding="utf-8"))
    verdicts: Counter[Verdict] = Counter()
    reasons: dict[Verdict, Counter[str]] = {verdict: Counter() for verdict in Verdict}
    unfinished: list[str] = []
    lines: list[str] = []
    for job_id in run["jobs"]:
        if not (run_dir / job_id / RESULT_FILE).is_file():
            unfinished.append(job_id)
            continue
        result = JobResult.read(run_dir / job_id)
        verdicts[result.verdict] += 1
        if result.reason is not None:
            reasons[result.verdict][result.reason.value] += 1
        suffix = f" ({result.reason.value})" if result.reason else ""
        lines.append(
            f"  {job_id}: {result.verdict.value}{suffix} attempts={result.attempts} "
            f"files={len(result.changed_files)} {result.seconds:.1f}s"
        )

    def count(verdict: Verdict) -> str:
        detail = ", ".join(
            f"{name} {n}" for name, n in sorted(reasons[verdict].items())
        )
        return f"{verdicts[verdict]}" + (f" ({detail})" if detail else "")

    wall = run["wall_seconds"]
    header = [
        f"run {run['name']} ({run['backend']} {run['model']}): {run_dir}",
        (
            f"jobs {len(run['jobs'])}  accepted {count(Verdict.ACCEPTED)}  "
            f"rejected {count(Verdict.REJECTED)}  worker-failed {count(Verdict.WORKER_FAILED)}  "
            f"timeout {count(Verdict.TIMEOUT)}  unfinished {len(unfinished)}"
        ),
        "wall " + ("unfinished" if wall is None else f"{wall:.1f}s"),
    ]
    return header + lines + [f"  {job_id}: unfinished" for job_id in unfinished]
