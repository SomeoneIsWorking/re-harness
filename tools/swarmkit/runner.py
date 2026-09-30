"""Run jobs: worktree, worker, gate, optional feedback retries, verdict on disk.

A job starts as soon as one of the run's ``workers`` is free; nothing else is
admitted or queued. Every process group a job starts (its worker, its gate) is
registered as a unit (``units``), so the machine's pressure guard can pause the
newest one if the host really runs out of memory. Per-kind slots and predicted
memory reservations were removed on 2026-09-30: they queued gates for up to 50
minutes while the host had 7 GiB free and half its cores idle.

Every unit, worker and gate alike, runs under the reaper (``process.run_bounded``),
so nothing it starts outlives the job.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .backends import Backend
from .console import emit
from .jobs import Job
from .lifetime import RunLifetime
from .process import ProcessOutcome, run_bounded
from .results import PATCH_FILE, RESULT_FILE, RUN_FILE, JobResult, Reason, Verdict
from .units import UnitRegistry
from .worktree import Worktree, WorktreeError, run_directory

TREE_DIR = "tree"
TASK_FILE = "prompt-{attempt}.md"
FEEDBACK = (
    "\n\n---\nYour previous attempt was rejected by the gate `{gate}` (exit {code}). "
    "Its output ends with:\n```\n{tail}\n```\nFix the cause and try again. "
    "The worktree still contains your previous changes."
)
RESUMED = (
    "\n\n---\nThis job was interrupted part-way through an earlier attempt. The current "
    "directory still holds that attempt's unfinished changes: read `git diff` and "
    "`git status` first and continue from them; do not start over."
)
EMPTY_FEEDBACK = (
    "\n\n---\nYour previous attempt changed no files, so nothing could be accepted. "
    "Make the change in the files of the current directory."
)


@dataclass(frozen=True)
class RunSettings:
    backend: Backend
    model: str
    retries: int
    units: UnitRegistry
    lifetime: RunLifetime


class JobRunner:
    def __init__(
        self, run_name: str, settings: RunSettings, resume: bool = False
    ) -> None:
        self.run_name = run_name
        self.settings = settings
        self.resume = resume

    def job_dir(self, job: Job) -> Path:
        return run_directory(job.repo, self.run_name) / job.id

    def run(self, job: Job) -> JobResult:
        job_dir = self.job_dir(job)
        if self.resume and (job_dir / RESULT_FILE).is_file():
            # A worker failure was never judged by the gate, so it continues like an
            # unfinished job; every judged verdict stands.
            result = JobResult.read(job_dir)
            if result.verdict is not Verdict.WORKER_FAILED:
                emit(
                    f"swarm: {job.id}: kept {result.verdict.value} from the interrupted run"
                )
                return result
        job_dir.mkdir(parents=True, exist_ok=self.resume)
        started = time.monotonic()
        result = self._run_job(job, job_dir)
        result.seconds = round(time.monotonic() - started, 3)
        result.write(job_dir)
        emit(
            f"swarm: {job.id}: {result.verdict.value}"
            + (f" ({result.reason.value})" if result.reason else "")
        )
        return result

    def _run_job(self, job: Job, job_dir: Path) -> JobResult:
        tree_path = job_dir / TREE_DIR
        resumed = self.resume and tree_path.exists()
        try:
            if resumed:
                tree = Worktree.reopen(job.repo, tree_path)
            else:
                tree = Worktree.create(job.repo, tree_path)
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
        # An interrupted attempt keeps its log; the resumed one is numbered after it
        # and does not count against the retries.
        first = 1 + len(list(job_dir.glob("worker-*.log")))
        prompt = job.prompt + RESUMED if resumed else job.prompt
        result: JobResult | None = None
        for attempt in range(first, first + self.settings.retries + 1):
            result = self._attempt(job, job_dir, tree, prompt, attempt)
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

    def _attempt(
        self,
        job: Job,
        job_dir: Path,
        tree: Worktree,
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
                list(job.gate),
                **fields,
            )

        lifetime = self.settings.lifetime
        task_file = job_dir / TASK_FILE.format(attempt=attempt)
        task_file.write_text(prompt, encoding="utf-8")
        emit(f"swarm: {job.id}: worker attempt {attempt}")
        # Attach from the worker's own checkout, by absolute path so no CLI guesses the base.
        # Only files that exist now: a job may create a listed file, and a retry runs on the
        # tree the last attempt left, where a listed file may be deleted. opencode refuses to
        # start when asked to attach a missing file. The task file lives outside the worktree,
        # so the job's own directory joins read_only and the worker may read it, not edit it.
        files = [
            str(tree.path / name) for name in job.files if (tree.path / name).is_file()
        ]
        worker = self._run_unit(
            "swarm",
            self.settings.backend.command(task_file, files, self.settings.model),
            tree.path,
            job.timeout,
            job_dir / f"worker-{attempt}.log",
            lifetime,
            {
                **tree.cache_environment(),
                **self.settings.backend.environment([*job.read_only, job_dir]),
            },
        )
        if worker.timed_out:
            return verdict(Verdict.TIMEOUT, Reason.WORKER, worker_tail=worker.tail())
        # Snapshot before the gate so build products the gate writes never enter the patch.
        patch, changed = tree.capture_patch()
        (job_dir / PATCH_FILE).write_text(patch, encoding="utf-8")
        # A worker's exit status does not judge its work; the gate does. opencode exits 1
        # after recovering from a transient provider error mid-session, and treating that
        # as failure discarded half of one psx batch's finished overrides ungated. Only a
        # worker that also changed nothing has failed.
        if worker.returncode != 0 and not changed:
            return verdict(
                Verdict.WORKER_FAILED,
                Reason.WORKER_EXIT,
                worker_returncode=worker.returncode,
                worker_tail=worker.tail(),
            )
        if not changed:
            return verdict(Verdict.REJECTED, Reason.EMPTY_PATCH, worker_returncode=0)
        gate = self._run_unit(
            "swarm",
            job.gate,
            tree.path,
            job.gate_timeout,
            job_dir / f"gate-{attempt}.log",
            lifetime,
            tree.cache_environment(),
        )
        common = {
            "worker_returncode": worker.returncode,
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

    def _run_unit(self, kind: str, *args, **kwargs) -> ProcessOutcome:
        """``run_bounded`` with the new process group registered as a unit while it runs."""
        units = []

        def started(group: int) -> None:
            units.append(self.settings.units.register(group, kind))

        try:
            return run_bounded(*args, **kwargs, on_spawn=started)
        finally:
            for unit in units:
                self.settings.units.remove(unit)


def run_jobs(
    jobs: Sequence[Job],
    run_name: str,
    settings: RunSettings,
    workers: int,
    resume: bool = False,
) -> list[JobResult]:
    """Run every job with at most ``workers`` in flight; write ``run.json`` per repository.

    With ``resume`` the run continues an interrupted one of the same name: a job the gate
    judged keeps its verdict, an unfinished or worker-failed job continues in the worktree
    it left, and a job that never started starts fresh. Without it an existing job directory is refused.
    """
    runner = JobRunner(run_name, settings, resume)
    run_dirs: dict[Path, list[str]] = {}
    for job in jobs:
        directory = run_directory(job.repo, run_name)
        if not resume and (directory / job.id).exists():
            raise FileExistsError(
                f"{directory / job.id} already exists; choose another --name, "
                "or pass --resume to continue that run"
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
