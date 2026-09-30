"""Run jobs: worktree, worker, gate, optional feedback retries, verdict on disk.

Each job runs under two machine-wide claims: a slot (how many) and a memory
reservation (how much it may still grow into). The reservation is taken once for
the job, sized for the larger of the worker's and the gate's peak, and attached to
every process group the job starts, so the headroom the ledger keeps free covers
both. A heavy gate therefore takes no reservation of its own: a second one was
refused by the job's own idle worker entry, and the job waited on itself.

A heavy gate is admitted here, in the runner, through the machine's build slots,
and its ``gate_timeout`` starts only once it holds one. Run through ``heavy.py``
the admission wait sat inside the gate's deadline, so a gate queued behind other
builds timed out without ever running.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import config
from .admission import MachineSlots, SlotLease
from .backends import Backend
from .console import emit
from .jobs import Job
from .lifetime import RunLifetime
from .pressure import PressureWatcher
from .process import run_bounded
from .reaper import command_argv, command_environment_overrides
from .reservations import Reservation, ReservationLedger
from .results import PATCH_FILE, RUN_FILE, JobResult, Reason, Verdict
from .worktree import Worktree, WorktreeError, run_directory

TREE_DIR = "tree"
TASK_FILE = "prompt-{attempt}.md"
FEEDBACK = (
    "\n\n---\nYour previous attempt was rejected by the gate `{gate}` (exit {code}). "
    "Its output ends with:\n```\n{tail}\n```\nFix the cause and try again. "
    "The worktree still contains your previous changes."
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
    slots: MachineSlots
    gate_slots: MachineSlots
    memory: ReservationLedger
    pressure: PressureWatcher
    reserve_mib: int
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
        with (
            self.settings.slots.acquire(self.settings.lifetime),
            self.settings.memory.acquire(
                self.settings.lifetime, self._reserve_mib(job), "swarm"
            ) as reservation,
        ):
            result = self._run_in_slot(job, job_dir, reservation)
        result.seconds = round(time.monotonic() - started, 3)
        result.write(job_dir)
        emit(
            f"swarm: {job.id}: {result.verdict.value}"
            + (f" ({result.reason.value})" if result.reason else "")
        )
        return result

    def _reserve_mib(self, job: Job) -> int:
        """The job's one reservation: its worker's peak or its heavy gate's, whichever is larger."""
        if not job.heavy_gate:
            return self.settings.reserve_mib
        gate_mib = job.mem_mib or config.HEAVY_RESERVE_MIB["build"]
        return max(self.settings.reserve_mib, gate_mib)

    def _run_in_slot(
        self, job: Job, job_dir: Path, reservation: Reservation
    ) -> JobResult:
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
        prompt = job.prompt
        result: JobResult | None = None
        for attempt in range(1, self.settings.retries + 2):
            result = self._attempt(
                job, job_dir, tree, prompt, attempt, reservation
            )
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
        reservation: Reservation,
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
        files = [str(tree.path / name) for name in job.files if (tree.path / name).is_file()]
        worker = run_bounded(
            self.settings.backend.command(task_file, files, self.settings.model),
            tree.path,
            job.timeout,
            job_dir / f"worker-{attempt}.log",
            lifetime,
            self.settings.backend.environment([*job.read_only, job_dir]),
            on_spawn=self._unit_started(reservation),
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
        with self._gate_admission(job):
            argv, environment = self._gate_command(job)
            gate = run_bounded(
                argv,
                tree.path,
                job.gate_timeout,
                job_dir / f"gate-{attempt}.log",
                lifetime,
                environment,
                on_spawn=self._unit_started(reservation),
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

    @contextmanager
    def _gate_admission(self, job: Job) -> Iterator[None]:
        """Hold one build slot around a heavy gate; a light gate needs none."""
        if not job.heavy_gate:
            yield
            return
        slots = self.settings.gate_slots
        lease: SlotLease | None = slots.try_acquire()
        if lease is None:
            emit(f"swarm: {job.id}: all {slots.count} build slots busy; gate waiting")
            lease = slots.acquire(self.settings.lifetime)
        with lease:
            yield

    @staticmethod
    def _gate_command(job: Job) -> tuple[list[str], dict[str, str] | None]:
        """A heavy gate runs under the reaper, so its whole subtree dies with it."""
        if not job.heavy_gate:
            return list(job.gate), None
        return command_argv(job.gate), command_environment_overrides()

    def _unit_started(self, reservation: Reservation) -> Callable[[int], None]:
        """Name a job's new process group for the ledger and the pressure watcher."""

        def started(group: int) -> None:
            reservation.attach(group)
            self.settings.pressure.adopt(group)

        return started


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
