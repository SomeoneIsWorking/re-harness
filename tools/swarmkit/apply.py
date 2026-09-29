"""Apply an accepted patch to the job's main working tree, refusing on conflict."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .results import PATCH_FILE, JobResult, Verdict


class ApplyRefused(RuntimeError):
    """The patch was not applied; the main tree is unchanged."""


def apply_accepted(run_dir: Path, job_id: str) -> JobResult:
    job_dir = run_dir / job_id
    result = JobResult.read(job_dir)
    if result.verdict is not Verdict.ACCEPTED:
        raise ApplyRefused(f"{job_id} is {result.verdict.value}, not accepted")
    patch = job_dir / PATCH_FILE
    if not patch.is_file() or patch.stat().st_size == 0:
        raise ApplyRefused(f"{patch} is missing or empty")
    repo = Path(result.repo)
    for check in (["--check"], []):
        done = subprocess.run(
            ["git", "-C", str(repo), "apply", *check, str(patch.resolve())],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise ApplyRefused(
                f"git apply {' '.join(check)} in {repo}: {done.stderr.strip()}"
            )
    return result
