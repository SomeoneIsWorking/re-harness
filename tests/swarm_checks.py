"""Positive and negative controls for tools/swarm.py, driven through its shipping modules.

A fake backend (``swarm_fake_worker.py``) stands in for the model so every
verdict -- accepted, rejected, worker-failed, timeout -- is produced on demand.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from signal import SIGCONT, SIGSTOP

HERE = Path(__file__).resolve().parent
FAKE_WORKER = HERE / "swarm_fake_worker.py"
sys.path.insert(0, str(HERE.parent / "tools"))

from swarmkit.admission import MachineSlots
from swarmkit.apply import ApplyRefused, apply_accepted
from swarmkit.backends import BACKENDS, PROMPT_ATTACHED
from swarmkit.cleanup import CleanupRefused, remove_worktrees
from swarmkit.config import HEAVY_SLOTS
from swarmkit.jobs import Job, JobFileError, load_jobs
from swarmkit.lifetime import RunInterrupted, RunLifetime
from swarmkit.pressure import PressureWatcher
from swarmkit.process import ProcessOutcome, run_bounded
from swarmkit.procs import MIB
from swarmkit.report import summarize
from swarmkit.reservations import ReservationLedger
from swarmkit.results import JobResult, Reason, Verdict
from swarmkit.runner import RunSettings, run_jobs
from swarmkit.worktree import WorktreeError, registered_worktrees

Check = Callable[..., int]
PY = sys.executable


class FakeBackend:
    name = "fake"

    def command(
        self, task_file: Path, files: Sequence[str], model: str
    ) -> list[str]:
        return [PY, str(FAKE_WORKER), str(task_file), *files]

    def environment(self, read_only: Sequence[Path]) -> dict[str, str]:
        return {}


def make_repo(root: Path, ignore_scratch: bool = True) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / ".gitignore").write_text(
        "scratch/\n" if ignore_scratch else "", encoding="utf-8"
    )
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return repo


def settings(root: Path, slots: int = 8, retries: int = 0) -> RunSettings:
    return RunSettings(
        backend=FakeBackend(),
        model="fake",
        retries=retries,
        heavy_lock_dir=root / "locks",
        slots=MachineSlots(root / "locks" / "slots", slots, poll_seconds=0.05),
        memory=ReservationLedger(
            root / "locks",
            0,
            reader=lambda: 64 * MIB,
            rss_reader=lambda groups: {group: 0 for group in groups},
            poll_seconds=0.05,
        ),
        pressure=PressureWatcher(0, 0, reader=lambda: 64 * MIB),
        reserve_mib=1,
        lifetime=RunLifetime(),
    )


def gate_file_is(name: str, text: str) -> tuple[str, ...]:
    code = (
        f"import sys; t=open({name!r}).read().strip(); print('gate saw', repr(t)); "
        f"sys.exit(0 if t=={text!r} else 1)"
    )
    return (PY, "-c", code)


def job(repo: Path, job_id: str, prompt: str, gate: Sequence[str], **extra) -> Job:
    return Job(
        id=job_id,
        repo=repo,
        prompt=prompt,
        gate=tuple(gate),
        timeout=extra.pop("timeout", 30.0),
        **extra,
    )


def process_gone(pid: int, wait_seconds: float = 3.0) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


def run_checks(check: Check, scratch: str) -> int:
    fails = 0
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _verdict_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _admission_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _interrupt_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _input_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _reservation_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _pressure_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _deadline_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _task_file_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _heavy_checks(check, Path(tmp))
    fails += _backend_checks(check)
    return fails


def _verdict_checks(check: Check, root: Path) -> int:
    fails = 0
    repo = make_repo(root)
    pidfile = root / "orphan.pid"
    jobs = [
        job(repo, "accept", "write hello.txt hi", gate_file_is("hello.txt", "hi")),
        job(repo, "reject", "write hello.txt wrong", gate_file_is("hello.txt", "hi")),
        job(
            repo,
            "gate-nonzero",
            "write hello.txt hi",
            (PY, "-c", "raise SystemExit(3)"),
        ),
        job(repo, "timeout", f"orphan {pidfile}", gate_file_is("x", "x"), timeout=1.0),
        job(repo, "worker-fail", "fail 5", gate_file_is("x", "x")),
        job(repo, "empty", "noop", (PY, "-c", "pass")),
    ]
    results = {r.id: r for r in run_jobs(jobs, "verdicts", settings(root), workers=6)}
    run_dir = repo / "scratch" / "swarm" / "verdicts"

    accepted = results["accept"]
    patch = (run_dir / "accept" / "patch.diff").read_text()
    fails += check(
        "swarm: gate exit 0 is accepted with its patch",
        accepted.verdict is Verdict.ACCEPTED
        and "+hi" in patch
        and accepted.changed_files == ["hello.txt"],
        json.dumps(accepted.__dict__, default=str),
    )
    fails += check(
        "swarm: the main tree is untouched by workers",
        not (repo / "hello.txt").exists(),
    )
    rejected = results["reject"]
    fails += check(
        "swarm: failing gate is rejected with its tail",
        rejected.verdict is Verdict.REJECTED
        and rejected.reason is Reason.GATE_FAILED
        and "gate saw 'wrong'" in rejected.gate_tail,
        rejected.gate_tail,
    )
    nonzero = results["gate-nonzero"]
    on_disk = JobResult.read(run_dir / "gate-nonzero")
    fails += check(
        "swarm: NEGATIVE nonzero gate is never accepted",
        nonzero.verdict is not Verdict.ACCEPTED
        and on_disk.verdict is not Verdict.ACCEPTED
        and on_disk.gate_returncode == 3,
    )
    try:
        JobResult(
            "forged", str(repo), "", Verdict.ACCEPTED, None, 1, [], gate_returncode=3
        )
        forged = True
    except ValueError:
        forged = False
    fails += check(
        "swarm: NEGATIVE an accepted record with gate exit 3 cannot exist", not forged
    )
    timed = results["timeout"]
    orphan = int(pidfile.read_text()) if pidfile.exists() else -1
    fails += check(
        "swarm: worker past its deadline is a timeout",
        timed.verdict is Verdict.TIMEOUT and timed.reason is Reason.WORKER,
    )
    fails += check(
        "swarm: timeout kills the worker's whole process group",
        orphan > 0 and process_gone(orphan),
        f"orphan pid {orphan}",
    )
    failed = results["worker-fail"]
    fails += check(
        "swarm: nonzero worker exit is worker-failed without a gate",
        failed.verdict is Verdict.WORKER_FAILED
        and failed.worker_returncode == 5
        and failed.gate_returncode is None
        and not (run_dir / "worker-fail" / "gate-1.log").exists(),
    )
    empty = results["empty"]
    fails += check(
        "swarm: a worker that changes nothing is rejected (empty-patch)",
        empty.verdict is Verdict.REJECTED and empty.reason is Reason.EMPTY_PATCH,
    )

    report = "\n".join(summarize(run_dir))
    fails += check(
        "swarm: report prints denominators",
        "jobs 6  accepted 1  rejected 3 (empty-patch 1, gate-failed 2)  "
        "worker-failed 1 (worker-exit 1)  timeout 1 (worker 1)  unfinished 0" in report,
        report,
    )

    env_repo = make_repo(root / "env")
    located = {
        r.id: r
        for r in run_jobs(
            [
                job(env_repo, "pwd", "envpwd", gate_file_is("pwd.txt", "pwd")),
                job(
                    env_repo,
                    "files",
                    "attached",
                    gate_file_is("attached.txt", "ok"),
                    files=("base.txt", "created-by-the-job.txt"),
                ),
            ],
            "env",
            settings(root),
            workers=2,
        )
    }
    fails += check(
        "swarm: $PWD of a worker is its worktree",
        located["pwd"].verdict is Verdict.ACCEPTED
        and not (env_repo / "pwd.txt").exists(),
    )
    fails += check(
        "swarm: attachments are absolute paths inside the worktree, and only files that exist",
        located["files"].verdict is Verdict.ACCEPTED,
        located["files"].gate_tail,
    )

    retry_repo = make_repo(root / "retry")
    retried = run_jobs(
        [job(retry_repo, "fixup", "retry out.txt", gate_file_is("out.txt", "good"))],
        "retry",
        settings(root, retries=2),
        workers=1,
    )[0]
    fails += check(
        "swarm: gate feedback re-prompt converts a rejection",
        retried.verdict is Verdict.ACCEPTED and retried.attempts == 2,
        f"{retried.verdict} attempts={retried.attempts}",
    )
    no_retry = run_jobs(
        [job(retry_repo, "fixup", "retry out.txt", gate_file_is("out.txt", "good"))],
        "noretry",
        settings(root, retries=0),
        workers=1,
    )[0]
    fails += check(
        "swarm: without retries the same job stays rejected",
        no_retry.verdict is Verdict.REJECTED and no_retry.attempts == 1,
    )

    try:
        apply_accepted(run_dir, "reject")
        refused_rejected = False
    except ApplyRefused:
        refused_rejected = True
    fails += check("swarm: apply refuses a rejected job", refused_rejected)
    apply_accepted(run_dir, "accept")
    fails += check(
        "swarm: apply writes an accepted patch into the main tree",
        (repo / "hello.txt").read_text() == "hi\n",
    )
    (repo / "hello.txt").write_text("local edit\n")
    try:
        apply_accepted(run_dir, "accept")
        conflict_refused = False
    except ApplyRefused:
        conflict_refused = True
    fails += check(
        "swarm: apply refuses on conflict and leaves the tree as it was",
        conflict_refused and (repo / "hello.txt").read_text() == "local edit\n",
    )

    before = registered_worktrees(repo)
    removed = remove_worktrees(run_dir)
    after = registered_worktrees(repo)
    fails += check(
        "swarm: gc removes exactly the run's worktrees",
        removed == 6
        and len(before) - len(after) == 6
        and (run_dir / "accept" / "result.json").exists()
        and not (run_dir / "accept" / "tree").exists(),
        f"removed {removed}",
    )
    try:
        remove_worktrees(repo)
        gc_refused = False
    except CleanupRefused:
        gc_refused = True
    fails += check("swarm: gc refuses a directory that is not a run", gc_refused)
    return fails


def _admission_checks(check: Check, root: Path) -> int:
    fails = 0
    repo = make_repo(root)
    events = root / "events.txt"
    jobs = [
        job(repo, f"j{i}", f"overlap {events} 0.4", (PY, "-c", "pass"))
        for i in range(6)
    ]
    run_jobs(jobs, "cap", settings(root, slots=2), workers=6)
    stamps = sorted(
        (float(t), 1 if s == "+" else -1)
        for s, t in (line.split() for line in events.read_text().splitlines())
    )
    level = peak = 0
    for _, delta in stamps:
        level += delta
        peak = max(peak, level)
    fails += check(
        "swarm: machine slots cap concurrency (6 jobs, 6 workers, 2 slots)",
        peak == 2,
        f"peak {peak}",
    )

    slots = MachineSlots(root / "held", 2)
    first, second = slots.try_acquire(), slots.try_acquire()
    third = slots.try_acquire()
    fails += check(
        "swarm: a full slot set admits nobody", first and second and third is None
    )
    assert first is not None
    first.release()
    fourth = slots.try_acquire()
    fails += check("swarm: a released slot is reusable", fourth is not None)

    build_slots = MachineSlots(root / "locks" / "heavy-build", HEAVY_SLOTS["build"])
    holders = [build_slots.try_acquire() for _ in range(HEAVY_SLOTS["build"])]
    heavy = job(
        repo,
        "heavy",
        "write h.txt x",
        (PY, "-c", "pass"),
        heavy_gate=True,
        gate_timeout=1.0,
    )
    light = job(repo, "light", "write h.txt x", (PY, "-c", "pass"), gate_timeout=1.0)
    held = {
        r.id: r for r in run_jobs([heavy, light], "heavy", settings(root), workers=2)
    }
    for holder in holders:
        assert holder is not None
        holder.release()
    fails += check(
        "swarm: a heavy gate waits while every build slot is held",
        held["heavy"].verdict is Verdict.TIMEOUT
        and held["heavy"].reason is Reason.GATE
        and "heavy.py" in held["heavy"].gate[1],
    )
    fails += check(
        "swarm: a light gate ignores the heavy lock",
        held["light"].verdict is Verdict.ACCEPTED,
    )
    return fails


def _interrupt_checks(check: Check, root: Path) -> int:
    fails = 0
    repo = make_repo(root)
    pidfile = root / "orphan.pid"
    run_settings = settings(root)
    outcome: list[BaseException] = []

    def target() -> None:
        try:
            run_jobs(
                [
                    job(
                        repo,
                        "hang",
                        f"orphan {pidfile}",
                        (PY, "-c", "pass"),
                        timeout=60.0,
                    )
                ],
                "stopped",
                run_settings,
                workers=1,
            )
        except BaseException as error:  # noqa: BLE001 -- the check inspects it
            outcome.append(error)

    thread = threading.Thread(target=target)
    thread.start()
    deadline = time.time() + 10
    while not pidfile.exists() and time.time() < deadline:
        time.sleep(0.05)
    started = time.time()
    run_settings.lifetime.stop()
    thread.join(timeout=15)
    orphan = int(pidfile.read_text()) if pidfile.exists() else -1
    fails += check(
        "swarm: stopping a run kills in-flight groups promptly",
        not thread.is_alive()
        and time.time() - started < 10
        and orphan > 0
        and process_gone(orphan),
    )
    fails += check(
        "swarm: an interrupted job has no verdict (report: unfinished)",
        bool(outcome)
        and isinstance(outcome[0], RunInterrupted)
        and not (repo / "scratch/swarm/stopped/hang/result.json").exists()
        and "unfinished 1" in "\n".join(summarize(repo / "scratch/swarm/stopped")),
        repr(outcome),
    )

    slots = MachineSlots(root / "full", 1, poll_seconds=0.05)
    holder = slots.try_acquire()
    lifetime = RunLifetime()
    waited: list[BaseException] = []

    def waiter() -> None:
        try:
            slots.acquire(lifetime)
        except RunInterrupted as error:
            waited.append(error)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.2)
    lifetime.stop()
    thread.join(timeout=5)
    assert holder is not None
    holder.release()
    fails += check("swarm: a slot wait gives up when the run stops", len(waited) == 1)
    return fails


def _input_checks(check: Check, root: Path) -> int:
    fails = 0
    good = {"id": "a", "repo": ".", "prompt": "p", "gate": ["true"], "timeout": 5}
    cases = {
        "missing gate": {k: v for k, v in good.items() if k != "gate"},
        "path id": dict(good, id="../x"),
        "zero timeout": dict(good, timeout=0),
        "unknown field": dict(good, gates=["true"]),
    }
    jobs_file = root / "jobs.jsonl"
    jobs_file.write_text(json.dumps(good) + "\n")
    fails += check(
        "swarm: a valid jobs file loads", load_jobs(jobs_file)[0].repo == root.resolve()
    )
    for label, record in [*cases.items(), ("duplicate id", None)]:
        lines = [json.dumps(good)] * 2 if record is None else [json.dumps(record)]
        jobs_file.write_text("\n".join(lines) + "\n")
        try:
            load_jobs(jobs_file)
            refused = False
        except JobFileError:
            refused = True
        fails += check(f"swarm: jobs file refuses {label}", refused)

    (root / "generated").mkdir(exist_ok=True)
    jobs_file.write_text(json.dumps(dict(good, read_only=["generated"])) + "\n")
    fails += check(
        "swarm: read_only resolves against the job's repo",
        load_jobs(jobs_file)[0].read_only == ((root / "generated").resolve(),),
    )
    jobs_file.write_text(json.dumps(dict(good, read_only=["absent"])) + "\n")
    try:
        load_jobs(jobs_file)
        refused = False
    except JobFileError:
        refused = True
    fails += check("swarm: jobs file refuses a read_only directory that does not exist", refused)

    jobs_file.write_text(json.dumps(dict(good, heavy_gate=True, mem_mib=4096)) + "\n")
    fails += check(
        "swarm: mem_mib is a whole number of MiB that reaches the heavy gate",
        load_jobs(jobs_file)[0].mem_mib == 4096,
    )
    mem_cases = {
        "zero mem_mib": 0,
        "negative mem_mib": -8,
        "fractional mem_mib": 512.0,
        "text mem_mib": "512",
    }
    for label, value in mem_cases.items():
        jobs_file.write_text(
            json.dumps(dict(good, heavy_gate=True, mem_mib=value)) + "\n"
        )
        try:
            load_jobs(jobs_file)
            refused = False
        except JobFileError:
            refused = True
        fails += check(f"swarm: jobs file refuses {label}", refused)
    jobs_file.write_text(json.dumps(dict(good, mem_mib=4096)) + "\n")
    try:
        load_jobs(jobs_file)
        refused = False
    except JobFileError:
        refused = True
    fails += check(
        "swarm: jobs file refuses mem_mib on a gate with no heavy admission", refused
    )

    unignored = make_repo(root / "plain", ignore_scratch=False)
    try:
        run_jobs(
            [job(unignored, "x", "noop", ["true"])], "r", settings(root), workers=1
        )
        refused = False
    except WorktreeError:
        refused = True
    fails += check("swarm: refuses a repo whose scratch/ is not ignored", refused)
    return fails


def _live_group(seconds: float = 30.0) -> subprocess.Popen:
    """A real process in its own group, so liveness is the kernel's answer."""
    return subprocess.Popen(
        [PY, "-c", f"import time; time.sleep({seconds:g})"], start_new_session=True
    )


def _ledger(
    root: Path,
    available_mib: int,
    rss_mib: dict[int, int] | None = None,
    floor_mib: int = 1024,
    on_wait: Callable[[int, int], None] | None = None,
) -> ReservationLedger:
    """A ledger over fixed answers, so the headroom arithmetic is the only variable."""
    used = rss_mib if rss_mib is not None else {}
    return ReservationLedger(
        root / "locks",
        floor_mib,
        reader=lambda: available_mib * MIB,
        rss_reader=lambda groups: {group: used.get(group, 0) * MIB for group in groups},
        poll_seconds=0,
        on_wait=on_wait,
    )


def _reservation_checks(check: Check, root: Path) -> int:
    fails = 0
    free = _ledger(root, 4000)
    # 8000 MiB free, floor 1024, a 512 MiB worker: the headroom rule admits it.
    roomy = _ledger(root, 8000)
    with roomy.try_acquire(512, "swarm") as held:
        fails += check(
            "swarm: a unit is admitted when free memory covers its reserve and the floor",
            held is not None
            and roomy.outstanding_bytes() == 512 * MIB
            and list(roomy.directory.iterdir()),
            f"outstanding {roomy.outstanding_bytes()}",
        )
    fails += check(
        "swarm: a released reservation stops holding headroom",
        roomy.outstanding_bytes() == 0 and not list(roomy.directory.iterdir()),
    )

    # A live 3072 MiB build leaves 4000 - 3072 = 928 MiB for a 512 MiB worker
    # against a 1024 MiB floor: refused, even though 4000 MiB of MemAvailable is
    # four times the floor. That gap is exactly the bug the reservation closes.
    build_unit = _live_group()
    alone = free.try_acquire(512, "swarm")
    fails += check(
        "swarm: on the same host with nothing held, 4000 MiB of MemAvailable admits it",
        alone is not None,
    )
    assert alone is not None
    alone.release()
    with _ledger(root, 8000).try_acquire(3072, "build") as reservation:
        assert reservation is not None
        reservation.attach(build_unit.pid)
        tight = _ledger(root, 4000)
        fails += check(
            "swarm: NEGATIVE admission refuses while reservations exhaust the headroom",
            tight.try_acquire(512, "swarm") is None
            and len(list(tight.directory.iterdir())) == 1,
            f"{[p.name for p in tight.directory.iterdir()]}",
        )
        reservation.release()
        generous = _ledger(root, 4000)
        freed = generous.try_acquire(512, "swarm")
        fails += check(
            "swarm: the same unit is admitted once the outstanding reservation is released",
            freed is not None,
        )
        if freed is not None:
            freed.release()
    build_unit.kill()
    build_unit.wait()

    # The outstanding part is the peak a unit has not reached yet.
    rss: dict[int, int] = {}
    growing = _ledger(root, 8000, rss_mib=rss)
    unit = _live_group()
    with growing.try_acquire(512, "swarm") as reservation:
        assert reservation is not None
        reservation.attach(unit.pid)
        rss[unit.pid] = 0
        cold = growing.outstanding_bytes() // MIB
        rss[unit.pid] = 400
        warm = growing.outstanding_bytes() // MIB
        rss[unit.pid] = 900
        full = growing.outstanding_bytes() // MIB
    unit.kill()
    unit.wait()
    fails += check(
        "swarm: outstanding shrinks as a unit's RSS approaches its reserve, never below 0",
        (cold, warm, full) == (512, 112, 0),
        f"{cold}, {warm}, {full}",
    )

    # A crashed admitter's entry is ignored once its group is gone.
    victim = _live_group()
    dead = _ledger(root, 8000)
    with dead.try_acquire(3072, "build") as reservation:
        assert reservation is not None
        reservation.attach(victim.pid)
        counted = dead.outstanding_bytes() // MIB
        victim.kill()
        victim.wait()
        process_gone(victim.pid)
        admitted = _ledger(root, 5000).try_acquire(3072, "build")
    if admitted is not None:
        admitted.release()
    fails += check(
        "swarm: NEGATIVE an entry whose process group is dead is ignored, not counted",
        counted == 3072
        and dead.outstanding_bytes() == 0
        and admitted is not None,
        f"counted {counted}",
    )
    fails += check(
        "swarm: a dead entry is removed from the shared directory",
        not list(dead.directory.iterdir()),
    )

    # A wait that never becomes room is cancelled with the run, like a slot wait.
    holder = _live_group()
    with _ledger(root, 8000).try_acquire(3072, "build") as reservation:
        assert reservation is not None
        reservation.attach(holder.pid)
        waits: list[tuple[int, int]] = []
        waiting = _ledger(
            root, 4000, on_wait=lambda free, held: waits.append((free, held))
        )
        lifetime = RunLifetime()
        gave_up: list[BaseException] = []

        def waiter() -> None:
            try:
                waiting.acquire(lifetime, 512, "swarm")
            except RunInterrupted as error:
                gave_up.append(error)

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.2)
        lifetime.stop()
        thread.join(timeout=5)
    holder.kill()
    holder.wait()
    fails += check(
        "swarm: a reservation wait gives up when the run stops",
        len(gave_up) == 1
        and bool(waits)
        and all(wait == (4000 * MIB, 3072) for wait in waits),
        f"waits {waits[:2]}",
    )
    try:
        _ledger(root, 8000).try_acquire(0, "swarm")
        refused = False
    except ValueError:
        refused = True
    fails += check("swarm: a zero reservation is refused", refused)
    return fails


def _pressure_checks(check: Check, root: Path) -> int:
    fails = 0
    sent: list[tuple[int, int]] = []
    events: list[str] = []
    free_mib = [500]
    watcher = PressureWatcher(
        1024,
        2560,
        reader=lambda: free_mib[0] * MIB,
        on_event=events.append,
        stopper=lambda group, signum: sent.append((group, signum)),
    )
    units = [_live_group(), _live_group(), _live_group()]
    for unit in units:
        watcher.adopt(unit.pid)
    first_stop = watcher.poll()
    second_stop = watcher.poll()
    third_stop = watcher.poll()
    free_mib[0] = 4096
    resumed = watcher.poll()
    fails += check(
        "swarm: pressure pauses the newest unit first, then all but the last",
        [call[0] for call in sent[:2]] == [units[2].pid, units[1].pid]
        and all(call[1] == SIGSTOP for call in sent[:2])
        and third_stop == []
        and len(first_stop) == 1
        and len(second_stop) == 1,
        f"sent {sent[:2]}",
    )
    fails += check(
        "swarm: pressure resumes the paused groups oldest first once memory returns",
        [call[0] for call in sent[2:]] == [units[1].pid, units[2].pid]
        and all(call[1] == SIGCONT for call in sent[2:])
        and len(resumed) == 2,
        f"resumed {sent[2:]}",
    )
    fails += check(
        "swarm: a pause and a resume are reported with the memory that caused them",
        len(events) == 4
        and "paused" in events[0]
        and "500 MiB" in events[0]
        and "resumed" in events[2]
        and "4096 MiB" in events[2],
        "; ".join(events),
    )
    fails += check(
        "swarm: NEGATIVE a host between the thresholds changes nothing (no flapping)",
        PressureWatcher(
            1024, 2560, reader=lambda: 1500 * MIB, stopper=lambda g, s: sent.append((g, s))
        ).poll()
        == []
        and len(sent) == 4,
        f"sent {sent}",
    )
    for unit in units:
        unit.kill()
        unit.wait()

    # One unit on its own is never paused: with nothing else to pause, ending the
    # run is the operator's decision, not the watcher's.
    alone_sent: list[tuple[int, int]] = []
    alone = PressureWatcher(
        1024, 2560, reader=lambda: 100 * MIB, stopper=lambda g, s: alone_sent.append((g, s))
    )
    single = _live_group()
    alone.adopt(single.pid)
    quiet = alone.poll()
    quiet += alone.poll()
    single.kill()
    single.wait()
    fails += check(
        "swarm: NEGATIVE the last running unit is never paused",
        quiet == [] and alone_sent == [],
        f"{quiet} {alone_sent}",
    )
    # An ended unit is forgotten, so a later pressure decision counts live units only.
    reaped = PressureWatcher(
        1024, 2560, reader=lambda: 100 * MIB, stopper=lambda g, s: alone_sent.append((g, s))
    )
    gone, stays = _live_group(), _live_group()
    for unit in (gone, stays):
        reaped.adopt(unit.pid)
    gone.kill()
    gone.wait()
    process_gone(gone.pid)
    reaped.poll()
    fails += check(
        "swarm: an ended unit is forgotten, so the survivor is never the one to pause",
        alone_sent == [],
        f"{alone_sent}",
    )
    stays.kill()
    stays.wait()
    return fails


def _deadline_checks(check: Check, root: Path) -> int:
    """A paused unit is not working, so its deadline is extended by the pause."""
    fails = 0
    outcome = _run_sleeping_child(root, 2.0, timeout=1.0, paused_for=1.5)
    fails += check(
        "swarm: a unit paused under pressure still gets its full running budget",
        not outcome.timed_out and outcome.returncode == 0,
        f"timed_out={outcome.timed_out} returncode={outcome.returncode}",
    )
    unpaused = _run_sleeping_child(root, 2.0, timeout=1.0, paused_for=0.0)
    fails += check(
        "swarm: NEGATIVE the same unit without a pause is killed at its deadline",
        unpaused.timed_out and unpaused.returncode is None,
        f"timed_out={unpaused.timed_out} returncode={unpaused.returncode}",
    )
    return fails


def _run_sleeping_child(
    root: Path, seconds: float, timeout: float, paused_for: float
) -> ProcessOutcome:
    """Run ``sleep seconds`` under ``run_bounded``, stopped for ``paused_for`` mid-run."""
    group: list[int] = []

    def pause_later() -> None:
        deadline = time.time() + 5
        while not group and time.time() < deadline:
            time.sleep(0.02)
        if not group:
            return
        time.sleep(0.2)
        os.killpg(group[0], SIGSTOP)
        time.sleep(paused_for)
        try:
            os.killpg(group[0], SIGCONT)
        except ProcessLookupError:
            pass

    pauser = None
    if paused_for:
        pauser = threading.Thread(target=pause_later)
        pauser.start()
    try:
        return run_bounded(
            [PY, "-c", f"import time; time.sleep({seconds:g})"],
            root,
            timeout,
            root / "sleep.log",
            RunLifetime(),
            on_spawn=group.append,
        )
    finally:
        if pauser is not None:
            pauser.join(timeout=10)


def _task_file_checks(check: Check, root: Path) -> int:
    """The task is attached as a file, so a prompt over the 128 KiB argv limit still runs."""
    fails = 0
    big = "say " + ("x" * 200_000)
    task = root / "task.md"
    task.write_text(big, encoding="utf-8")
    fails += check(
        "swarm: the fixture really is over the 128 KiB argv limit",
        task.stat().st_size > 128 * 1024,
    )
    for name, attached in (("opencode", str(task)), ("pi", f"@{task}")):
        argv = BACKENDS[name].command(task, ["/w/a.c"], "opencode/space-bunny-free")
        size = sum(len(part) + 1 for part in argv)
        fails += check(
            f"swarm: {name} argv for a 200 KB task stays small and attaches the file",
            size < 4096
            and attached in argv
            and PROMPT_ATTACHED in argv
            and big not in " ".join(argv),
            f"{size} bytes: {argv[:4]}",
        )
    fails += check(
        "swarm: the attached file holds the exact task",
        task.read_text(encoding="utf-8") == big,
    )
    repo = make_repo(root / "big")
    expected = "say " + ("y" * 200_000)
    wanted = root / "expected.txt"
    wanted.write_text(expected, encoding="utf-8")
    compare = (
        "import sys; a=open('task.txt',encoding='utf-8').read(); "
        f"b=open({str(wanted)!r},encoding='utf-8').read(); "
        "print(len(a), len(b)); sys.exit(0 if a==b else 1)"
    )
    result = run_jobs(
        [
            Job(
                id="big",
                repo=repo,
                prompt=expected,
                gate=(PY, "-c", compare),
                timeout=30.0,
            )
        ],
        "big",
        settings(root),
        workers=1,
    )[0]
    written = repo / "scratch" / "swarm" / "big" / "big" / "prompt-1.md"
    fails += check(
        "swarm: a 200 KB task runs end to end through the file, not argv",
        result.verdict is Verdict.ACCEPTED and written.read_text() == expected,
        f"{result.verdict} {result.worker_tail[:200]}",
    )
    return fails


def _backend_checks(check: Check) -> int:
    config = json.loads(
        BACKENDS["opencode"].environment([Path("/ref")])["OPENCODE_CONFIG_CONTENT"]
    )["permission"]
    confined = check(
        "swarm: opencode denies outside paths (catch-all first) and reads, never edits, read_only",
        list(config["external_directory"].items()) == [("*", "deny"), ("/ref/**", "allow")]
        and list(config["edit"].items()) == [("*", "allow"), ("/ref/**", "deny")],
        str(config),
    )
    opencode = BACKENDS["opencode"].command(
        Path("/j/task.md"), ["a.c"], "opencode/space-bunny-free"
    )
    pi = BACKENDS["pi"].command(
        Path("/j/task.md"), ["a.c"], "opencode/space-bunny-free"
    )
    return confined + check(
        "swarm: opencode argv is standalone JSON with the task attached first",
        opencode
        == [
            "opencode",
            "run",
            "--standalone",
            "-m",
            "opencode/space-bunny-free",
            "--format",
            "json",
            "-f",
            "/j/task.md",
            "-f",
            "a.c",
            "--",
            PROMPT_ATTACHED,
        ],
        str(opencode),
    ) + check(
        "swarm: pi argv is print-mode, sessionless, with the task attached first",
        pi
        == [
            "pi",
            "-p",
            "--no-session",
            "--model",
            "opencode/space-bunny-free",
            "--",
            "@/j/task.md",
            "@a.c",
            PROMPT_ATTACHED,
        ],
        str(pi),
    )


HEAVY_CLI = HERE.parent / "tools" / "heavy.py"


def _heavy(
    locks: Path, *argv: str, timeout: float = 20.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PY, str(HEAVY_CLI), "--lock-dir", str(locks), *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _heavy_checks(check: Check, root: Path) -> int:
    fails = 0
    locks = root / "locks"
    fails += check(
        "heavy: the command's exit status is returned",
        _heavy(locks, "--", PY, "-c", "raise SystemExit(7)").returncode == 7,
    )
    fails += check(
        "heavy: NEGATIVE no command is refused",
        _heavy(locks, "--kind", "run").returncode == 2,
    )
    fails += check(
        "heavy: NEGATIVE a --mem-mib of zero is refused",
        _heavy(locks, "--mem-mib", "0", "--", PY, "-c", "pass").returncode == 2,
    )
    fails += check(
        "heavy: --mem-mib reserves for the command and is released when it ends",
        _heavy(locks, "--mem-mib", "512", "--", PY, "-c", "pass").returncode == 0
        and not list((locks / "reservations").iterdir()),
    )

    build = MachineSlots(locks / "heavy-build", HEAVY_SLOTS["build"])
    holders = [build.try_acquire() for _ in range(HEAVY_SLOTS["build"])]
    marker = root / "ran.txt"
    blocked = False
    try:
        _heavy(locks, "--", PY, "-c", f"open({str(marker)!r}, 'w')", timeout=1.5)
    except subprocess.TimeoutExpired:
        blocked = True
    fails += check(
        "heavy: NEGATIVE a build waits while every build slot is held",
        blocked and not marker.exists(),
    )
    fails += check(
        "heavy: a run is admitted while the build slots are full",
        _heavy(locks, "--kind", "run", "--", PY, "-c", "pass").returncode == 0,
    )
    for holder in holders:
        assert holder is not None
        holder.release()

    daemon = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    _heavy(locks, "--", PY, "-c", daemon)
    leases = [build.try_acquire() for _ in range(HEAVY_SLOTS["build"])]
    fails += check(
        "heavy: a daemon left by the command does not keep its slot",
        all(lease is not None for lease in leases),
    )
    for lease in leases:
        if lease is not None:
            lease.release()
    return fails


def main() -> int:
    """Run every check here, so this file is a gate on its own and not only via run.py."""
    scratch = HERE.parent / "scratch" / "tests"
    scratch.mkdir(parents=True, exist_ok=True)

    def report(name: str, ok: bool, detail: str = "") -> int:
        print("  %-46s %s" % (name[:46], "ok" if ok else "FAIL"))
        if not ok and detail:
            print("      " + detail.strip().replace("\n", "\n      ")[:600])
        return 0 if ok else 1

    fails = run_checks(report, str(scratch))
    print("swarm selftest: %s (%d check(s) failed)" % ("ok" if not fails else "FAIL", fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
