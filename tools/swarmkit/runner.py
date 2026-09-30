"""Run jobs: worktree, worker, gate, optional feedback retries, verdict on disk.

Each job runs under two machine-wide claims: a slot (how many) and a memory
reservation (how much it may still grow into). The reservation is taken once for
the job at the worker's peak and attached to every process group the job starts.
A heavy gate grows that same reservation to its own peak when it is admitted and
shrinks it back afterwards. Holding the gate's peak for the whole job left 7 GiB
reserved by workers using 40 MiB each and the host idle; a second, separate gate
reservation was refused by the job's own worker entry, so the job waited on
itself. Growing needs headroom only for the increase, so neither can recur.

A heavy gate is admitted here, in the runner, through the machine's build slots
(and a run slot too when it starts a game instance), and its ``gate_timeout``
starts only once it holds them. Run through ``heavy.py`` the admission wait sat
inside the gate's deadline, so a gate queued behind other builds timed out
without ever running. Every unit, worker and gate alike, runs under the reaper
(``process.run_bounded``), so nothing it starts outlives the job.
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
from .reservations import Reservation, ReservationLedger
from .results import PATCH_FILE, RESULT_FILE, RUN_FILE, JobResult, Reason, Verdict
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
    slots: MachineSlots
    build_slots: MachineSlots
    run_slots: MachineSlots
    memory: ReservationLedger
    pressure: PressureWatcher
    reserve_mib: int
    lifetime: RunLifetime


class JobRunner:
    def __init__(self, run_name: str, settings: RunSettings, resume: bool = False) -> None:
        self.run_name = run_name
        self.settings = settings
        self.resume = resume

    def job_dir(self, job: Job) -> Path:
        return run_directory(job.repo, self.run_name) / job.id

    def run(self, job: Job) -> JobResult:
        job_dir = self.job_dir(job)
        if self.resume and (job_dir / RESULT_FILE).is_file():
            result = JobResult.read(job_dir)
            emit(f"swarm: {job.id}: kept {result.verdict.value} from the interrupted run")
            return result
        job_dir.mkdir(parents=True, exist_ok=self.resume)
        started = time.monotonic()
        with (
            self.settings.slots.acquire(self.settings.lifetime),
            self.settings.memory.acquire(
                self.settings.lifetime, self.settings.reserve_mib, "swarm"
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

    def _run_in_slot(
        self, job: Job, job_dir: Path, reservation: Reservation
    ) -> JobResult:
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
            {
                **tree.cache_environment(),
                **self.settings.backend.environment([*job.read_only, job_dir]),
            },
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
        with self._gate_admission(job, reservation):
            gate = run_bounded(
                job.gate,
                tree.path,
                job.gate_timeout,
                job_dir / f"gate-{attempt}.log",
                lifetime,
                tree.cache_environment(),
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
    def _gate_admission(self, job: Job, reservation: Reservation) -> Iterator[None]:
        """Hold one slot of the gate's kind, then the gate's peak, around a heavy gate.

        A gate holds exactly one kind of slot, so a game run never occupies a build slot
        and no runner holds one kind while waiting for the other.
        """
        if job.heavy_gate is None:
            yield
            return
        slots = {"build": self.settings.build_slots, "run": self.settings.run_slots}
        with self._slot(job, slots[job.heavy_gate], job.heavy_gate):
            with self._gate_memory(job, reservation):
                yield

    @contextmanager
    def _gate_memory(self, job: Job, reservation: Reservation) -> Iterator[None]:
        """Grow the job's reservation to its gate's peak; shrink it back afterwards."""
        worker_mib = reservation.reserve_mib
        gate_mib = max(worker_mib, job.mem_mib or config.HEAVY_RESERVE_MIB[job.heavy_gate])
        memory = self.settings.memory
        memory.resize(self.settings.lifetime, reservation, gate_mib)
        try:
            yield
        finally:
            memory.try_resize(reservation, worker_mib)

    def _slot(self, job: Job, slots: MachineSlots, kind: str) -> SlotLease:
        lease = slots.try_acquire()
        if lease is None:
            emit(f"swarm: {job.id}: all {slots.count} {kind} slots busy; gate waiting")
            lease = slots.acquire(self.settings.lifetime)
        return lease

    def _unit_started(self, reservation: Reservation) -> Callable[[int], None]:
        """Name a job's new process group for the ledger and the pressure watcher."""

        def started(group: int) -> None:
            reservation.attach(group)
            self.settings.pressure.adopt(group)

        return started


def run_jobs(
    jobs: Sequence[Job],
    run_name: str,
    settings: RunSettings,
    workers: int,
    resume: bool = False,
) -> list[JobResult]:
    """Run every job with at most ``workers`` in flight; write ``run.json`` per repository.

    With ``resume`` the run continues an interrupted one of the same name: a job with a
    verdict keeps it, an unfinished job continues in the worktree it left, and a job
    that never started starts fresh. Without it an existing job directory is refused.
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
