"""Run jobs: worktree, worker, gate, optional feedback retries, verdict on disk."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .admission import MachineSlots, MemoryFloor
from .backends import Backend
from .console import emit
from .jobs import Job
from .lifetime import RunLifetime
from .process import run_bounded
from .results import PATCH_FILE, RUN_FILE, JobResult, Reason, Verdict
from .worktree import Worktree, WorktreeError, run_directory

TREE_DIR = "tree"
FEEDBACK = (
    "\n\n---\nYour previous attempt was rejected by the gate `{gate}` (exit {code}). "
    "Its output ends with:\n```\n{tail}\n```\nFix the cause and try again. "
    "The worktree still contains your previous changes."
)
EMPTY_FEEDBACK = (
    "\n\n---\nYour previous attempt changed no files, so nothing could be accepted. "
    "Make the change in the files of the current directory."
)


HEAVY_CLI = Path(__file__).resolve().parent.parent / "heavy.py"


@dataclass(frozen=True)
class RunSettings:
    backend: Backend
    model: str
    retries: int
    heavy_lock_dir: Path
    slots: MachineSlots
    memory: MemoryFloor
    lifetime: RunLifetime


class JobRunner:
    def __init__(self, run_name: str, settings: RunSettings) -> None:
        self.run_name = run_name
        self.settings = settings

    def job_dir(self, job: Job) -> Path:
        return run_directory(job.repo, self.run_name) / job.id

    def run(self, job: Job) -> JobResult:
        job_dir = self.job_dir(job)
        job_dir.mkdir(parents=True, exist_ok=False)
        started = time.monotonic()
        with self.settings.slots.acquire(self.settings.lifetime):
            result = self._run_in_slot(job, job_dir)
        result.seconds = round(time.monotonic() - started, 3)
        result.write(job_dir)
        emit(
            f"swarm: {job.id}: {result.verdict.value}"
            + (f" ({result.reason.value})" if result.reason else "")
        )
        return result

    def _run_in_slot(self, job: Job, job_dir: Path) -> JobResult:
        try:
            tree = Worktree.create(job.repo, job_dir / TREE_DIR)
        except WorktreeError as error:
            (job_dir / "setup.log").write_text(f"{error}\n", encoding="utf-8")
            return JobResult(
                job.id,
                str(job.repo),
                "",
                Verdict.WORKER_FAILED,
                Reason.SETUP,
                0,
                list(job.gate),
                worker_tail=str(error),
            )
        gate_argv = self._gate_argv(job)
        prompt = job.prompt
        result: JobResult | None = None
        for attempt in range(1, self.settings.retries + 2):
            result = self._attempt(job, job_dir, tree, gate_argv, prompt, attempt)
            if result.verdict is not Verdict.REJECTED:
                return result
            if result.reason is Reason.EMPTY_PATCH:
                prompt = job.prompt + EMPTY_FEEDBACK
            else:
                prompt = job.prompt + FEEDBACK.format(
                    gate=" ".join(job.gate),
                    code=result.gate_returncode,
                    tail=result.gate_tail,
                )
        assert result is not None
        return result

    def _gate_argv(self, job: Job) -> list[str]:
        if not job.heavy_gate:
            return list(job.gate)
        return [
            sys.executable,
            str(HEAVY_CLI),
            "--kind",
            "build",
            "--lock-dir",
            str(self.settings.heavy_lock_dir),
            "--",
            *job.gate,
        ]

    def _attempt(
        self,
        job: Job,
        job_dir: Path,
        tree: Worktree,
        gate_argv: Sequence[str],
        prompt: str,
        attempt: int,
    ) -> JobResult:
        def verdict(value: Verdict, reason: Reason | None, **fields) -> JobResult:
            return JobResult(
                job.id,
                str(job.repo),
                tree.base,
                value,
                reason,
                attempt,
                list(gate_argv),
                **fields,
            )

        lifetime = self.settings.lifetime
        self.settings.memory.wait(lifetime)
        emit(f"swarm: {job.id}: worker attempt {attempt}")
        # Attach from the worker's own checkout, by absolute path so no CLI guesses the base.
        files = [str(tree.path / name) for name in job.files]
        worker = run_bounded(
            self.settings.backend.command(prompt, files, self.settings.model),
            tree.path,
            job.timeout,
            job_dir / f"worker-{attempt}.log",
            lifetime,
            self.settings.backend.environment(job.read_only),
        )
        if worker.timed_out:
            return verdict(Verdict.TIMEOUT, Reason.WORKER, worker_tail=worker.tail())
        if worker.returncode != 0:
            return verdict(
                Verdict.WORKER_FAILED,
                Reason.WORKER_EXIT,
                worker_returncode=worker.returncode,
                worker_tail=worker.tail(),
            )
        # Snapshot before the gate so build products the gate writes never enter the patch.
        patch, changed = tree.capture_patch()
        (job_dir / PATCH_FILE).write_text(patch, encoding="utf-8")
        if not changed:
            return verdict(Verdict.REJECTED, Reason.EMPTY_PATCH, worker_returncode=0)
        gate = run_bounded(
            gate_argv,
            tree.path,
            job.gate_timeout,
            job_dir / f"gate-{attempt}.log",
            lifetime,
        )
        common = {
            "worker_returncode": 0,
            "changed_files": changed,
            "gate_tail": gate.tail(),
        }
        if gate.timed_out:
            return verdict(Verdict.TIMEOUT, Reason.GATE, **common)
        if gate.returncode == 0:
            return verdict(Verdict.ACCEPTED, None, gate_returncode=0, **common)
        return verdict(
            Verdict.REJECTED,
            Reason.GATE_FAILED,
            gate_returncode=gate.returncode,
            **common,
        )


def run_jobs(
    jobs: Sequence[Job], run_name: str, settings: RunSettings, workers: int
) -> list[JobResult]:
    """Run every job with at most ``workers`` in flight; write ``run.json`` per repository."""
    runner = JobRunner(run_name, settings)
    run_dirs: dict[Path, list[str]] = {}
    for job in jobs:
        directory = run_directory(job.repo, run_name)
        if (directory / job.id).exists():
            raise FileExistsError(
                f"{directory / job.id} already exists; choose another --name"
            )
        run_dirs.setdefault(directory, []).append(job.id)
    started = time.time()
    for directory, ids in run_dirs.items():
        _write_run(directory, run_name, settings, ids, started, None)
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        results = list(pool.map(runner.run, jobs))
    except BaseException:
        # Stop children first so worker threads return instead of pinning shutdown.
        settings.lifetime.stop()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown()
    finished = time.time()
    for directory, ids in run_dirs.items():
        _write_run(directory, run_name, settings, ids, started, finished)
        emit(f"swarm: run directory {directory}")
    return results


def _write_run(
    directory: Path,
    name: str,
    settings: RunSettings,
    ids: list[str],
    started: float,
    finished: float | None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "name": name,
        "backend": settings.backend.name,
        "model": settings.model,
        "retries": settings.retries,
        "jobs": ids,
        "started": started,
        "finished": finished,
        "wall_seconds": None if finished is None else round(finished - started, 3),
    }
    (directory / RUN_FILE).write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
