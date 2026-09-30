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
from signal import SIGCONT, SIGKILL, SIGSTOP, SIGTERM

HERE = Path(__file__).resolve().parent
FAKE_WORKER = HERE / "swarm_fake_worker.py"
sys.path.insert(0, str(HERE.parent / "tools"))

from swarmkit.apply import ApplyRefused, apply_accepted
from swarmkit.backends import BACKENDS, PROMPT_ATTACHED
from swarmkit.cleanup import CleanupRefused, remove_worktrees
from swarmkit.jobs import Job, JobFileError, load_jobs
from swarmkit.lifetime import RunInterrupted, RunLifetime
from swarmkit.pressure import PressureGuard
from swarmkit.process import ProcessOutcome, run_bounded
from swarmkit.procs import MIB, descendants
from swarmkit.report import summarize
from swarmkit.results import JobResult, Reason, Verdict
from swarmkit.runner import RunSettings, run_jobs
from swarmkit.units import UnitRegistry
from swarmkit.worktree import Worktree, WorktreeError, registered_worktrees

Check = Callable[..., int]
PY = sys.executable


class FakeBackend:
    name = "fake"

    def command(self, task_file: Path, files: Sequence[str], model: str) -> list[str]:
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


def settings(root: Path, retries: int = 0) -> RunSettings:
    return RunSettings(
        backend=FakeBackend(),
        model="fake",
        retries=retries,
        units=UnitRegistry(root / "locks"),
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
        fails += _unit_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _interrupt_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _resume_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _input_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _pressure_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _deadline_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _task_file_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _heavy_checks(check, Path(tmp))
    fails += _reaper_adoption_checks(check)
    fails += _backend_checks(check)
    return fails


def _verdict_checks(check: Check, root: Path) -> int:
    fails = 0
    repo = make_repo(root)
    pidfile = root / "orphan.pid"
    detached_file = root / "detached.pid"
    detached_hung_file = root / "detached-hung.pid"
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
        job(
            repo,
            "worker-fail-changed",
            "fail 1 w.txt done",
            gate_file_is("w.txt", "done"),
        ),
        job(repo, "empty", "noop", (PY, "-c", "pass")),
        job(
            repo,
            "detach",
            f"detach {detached_file}",
            gate_file_is("detach.txt", "detached"),
        ),
        job(
            repo,
            "detach-timeout",
            f"detach {detached_hung_file} hang",
            gate_file_is("x", "x"),
            timeout=1.0,
        ),
    ]
    results = {r.id: r for r in run_jobs(jobs, "verdicts", settings(root), workers=8)}
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
    detached = int(detached_file.read_text()) if detached_file.exists() else -1
    fails += check(
        "swarm: a setsid daemon a worker leaves behind dies with the worker",
        results["detach"].verdict is Verdict.ACCEPTED
        and detached > 0
        and process_gone(detached, 10.0),
        f"daemon pid {detached}",
    )
    hung = int(detached_hung_file.read_text()) if detached_hung_file.exists() else -1
    fails += check(
        "swarm: a setsid daemon of a timed-out worker dies with it",
        results["detach-timeout"].verdict is Verdict.TIMEOUT
        and hung > 0
        and process_gone(hung, 10.0),
        f"daemon pid {hung}",
    )
    failed = results["worker-fail"]
    recovered = results["worker-fail-changed"]
    fails += check(
        "swarm: a nonzero worker exit that changed files is still judged by the gate",
        recovered.verdict is Verdict.ACCEPTED
        and recovered.worker_returncode == 1
        and recovered.gate_returncode == 0,
    )
    fails += check(
        "swarm: NEGATIVE a nonzero worker exit that changed nothing is worker-failed without a gate",
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
        "jobs 9  accepted 3  rejected 3 (empty-patch 1, gate-failed 2)  "
        "worker-failed 1 (worker-exit 1)  timeout 2 (worker 2)  unfinished 0" in report,
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
                    "ccache",
                    "envpwd",
                    (
                        PY,
                        "-c",
                        "import os, sys; ok = open('ccache.txt').read().strip() == 'ok' "
                        "and os.environ.get('CCACHE_BASEDIR') == os.getcwd(); "
                        "sys.exit(0 if ok else 1)",
                    ),
                ),
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
        "swarm: worker and gate share ccache across worktrees (CCACHE_BASEDIR is the tree)",
        located["ccache"].verdict is Verdict.ACCEPTED,
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
        removed == 9
        and len(before) - len(after) == 9
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


def _unit_checks(check: Check, root: Path) -> int:
    """Nothing is admitted or queued; every running worker and gate is a registered unit."""
    fails = 0
    repo = make_repo(root)
    events = root / "events.txt"
    jobs = [
        job(repo, f"j{i}", f"overlap {events} 0.4", (PY, "-c", "pass"))
        for i in range(6)
    ]
    run_jobs(jobs, "wide", settings(root), workers=6)
    stamps = sorted(
        (float(t), 1 if s == "+" else -1)
        for s, t in (line.split() for line in events.read_text().splitlines())
    )
    level = peak = 0
    for _, delta in stamps:
        level += delta
        peak = max(peak, level)
    fails += check(
        "swarm: every requested worker runs at once (6 jobs, 6 workers, no machine cap)",
        peak == 6,
        f"peak {peak}",
    )

    units = root / "locks" / "units"
    worker_saw = root / "worker-units.json"
    gate_saw = root / "gate-units.json"
    census = (
        "import json, os, pathlib; "
        f"rows = [json.loads(p.read_text()) for p in pathlib.Path({str(units)!r}).glob('*.json')]; "
        f"pathlib.Path({str(gate_saw)!r}).write_text(json.dumps([rows, os.getpgrp()]))"
    )
    counted = job(repo, "units", f"units {units} {worker_saw}", (PY, "-c", census))
    (counted_result,) = run_jobs([counted], "units", settings(root), workers=1)
    worker_rows = json.loads(worker_saw.read_text()) if worker_saw.exists() else None
    gate_rows, gate_group = (
        json.loads(gate_saw.read_text()) if gate_saw.exists() else ([], -1)
    )
    fails += check(
        "swarm: a running worker and a running gate are each registered as a unit",
        counted_result.verdict is Verdict.ACCEPTED
        and worker_rows is not None
        and len(worker_rows) == 1
        and [row["group"] for row in gate_rows] == [gate_group],
        f"worker saw {worker_rows}, gate saw {gate_rows} in group {gate_group}",
    )
    fails += check(
        "swarm: NEGATIVE a finished job leaves no unit behind",
        not list(units.glob("*.json")),
        f"{sorted(p.name for p in units.glob('*.json'))}",
    )
    slow = job(
        repo,
        "slow-gate",
        "write h.txt x",
        (PY, "-c", "import time; time.sleep(30)"),
        gate_timeout=0.5,
    )
    (slow_result,) = run_jobs([slow], "slow-gate", settings(root), workers=1)
    fails += check(
        "swarm: NEGATIVE a gate still times out at its deadline",
        slow_result.verdict is Verdict.TIMEOUT and slow_result.reason is Reason.GATE,
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
    return fails


def _resume_checks(check: Check, root: Path) -> int:
    """A resumed run keeps verdicts, continues unfinished jobs in place, starts new ones."""
    fails = 0
    repo = make_repo(root)
    done = job(repo, "done", "write d.txt first", gate_file_is("d.txt", "first"))
    (first,) = run_jobs([done], "resumable", settings(root), workers=1)
    # An interrupted job: a worktree with the earlier attempt's partial work and its
    # worker log, but no verdict. That is what a killed run leaves behind.
    run_dir = repo / "scratch" / "swarm" / "resumable"
    tree = Worktree.create(repo, run_dir / "cut" / "tree")
    (tree.path / "c.txt").write_text("partial\n", encoding="utf-8")
    (run_dir / "cut" / "worker-1.log").write_text("killed\n", encoding="utf-8")
    cut = job(repo, "cut", "resume c.txt", gate_file_is("c.txt", "partial\nresumed"))
    # A worker that failed without a gate verdict: its edit is in the tree.
    crashed = job(repo, "crashed", "fail 3", gate_file_is("k.txt", "partial\nresumed"))
    (crashed_result,) = run_jobs(
        [crashed], "resumable", settings(root), workers=1, resume=True
    )
    crashed_tree = run_dir / "crashed" / "tree"
    (crashed_tree / "k.txt").write_text("partial\n", encoding="utf-8")
    crashed = job(
        repo, "crashed", "resume k.txt", gate_file_is("k.txt", "partial\nresumed")
    )
    new = job(repo, "new", "resume n.txt", gate_file_is("n.txt", "fresh"))
    changed = job(repo, "done", "write d.txt second", gate_file_is("d.txt", "second"))

    try:
        run_jobs([changed, cut], "resumable", settings(root), workers=2)
        refused = False
    except FileExistsError:
        refused = True
    fails += check(
        "swarm: NEGATIVE an existing run name is refused without --resume", refused
    )

    results = {
        r.id: r
        for r in run_jobs(
            [changed, cut, new, crashed],
            "resumable",
            settings(root),
            workers=4,
            resume=True,
        )
    }
    fails += check(
        "swarm: resume keeps a finished job's verdict without rerunning it",
        first.verdict is Verdict.ACCEPTED
        and results["done"].verdict is Verdict.ACCEPTED
        and results["done"].gate_tail == first.gate_tail,
    )
    fails += check(
        "swarm: resume continues an unfinished job in its worktree, told it was interrupted",
        results["cut"].verdict is Verdict.ACCEPTED
        and results["cut"].base == tree.base
        and (run_dir / "cut" / "worker-2.log").exists(),
    )
    fails += check(
        "swarm: resume retries a worker failure the gate never judged, in its tree",
        crashed_result.verdict is Verdict.WORKER_FAILED
        and results["crashed"].verdict is Verdict.ACCEPTED,
    )
    fails += check(
        "swarm: NEGATIVE a job that never started runs fresh under resume",
        results["new"].verdict is Verdict.ACCEPTED,
    )
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
    fails += check(
        "swarm: jobs file refuses a read_only directory that does not exist", refused
    )

    for field in ("heavy_gate", "mem_mib", "run_slot"):
        jobs_file.write_text(json.dumps(dict(good, **{field: "build"})) + "\n")
        try:
            load_jobs(jobs_file)
            refused = False
        except JobFileError:
            refused = True
        fails += check(
            f"swarm: jobs file refuses the removed admission field {field}", refused
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


def _proc_state(pid: int) -> str:
    """The kernel's one-letter state for ``pid``; empty once it has left ``/proc``."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except FileNotFoundError:
        return ""
    return stat.rsplit(")", 1)[-1].split()[0]


def _live_group(seconds: float = 30.0) -> subprocess.Popen:
    """A real process in its own group, so liveness is the kernel's answer."""
    return subprocess.Popen(
        [PY, "-c", f"import time; time.sleep({seconds:g})"], start_new_session=True
    )


def _pressure_checks(check: Check, root: Path) -> int:
    fails = 0
    sent: list[tuple[int, int]] = []
    free_mib = [500]
    guard = PressureGuard(
        1024,
        2560,
        reader=lambda: free_mib[0] * MIB,
        stopper=lambda group, signum: sent.append((group, signum)),
    )
    groups = [101, 102, 103]
    first_stop = guard.poll(groups)
    second_stop = guard.poll(groups)
    third_stop = guard.poll(groups)
    free_mib[0] = 4096
    resumed = guard.poll(groups)
    fails += check(
        "pressure: pauses the newest unit first, then all but the last",
        sent[:2] == [(103, SIGSTOP), (102, SIGSTOP)]
        and third_stop == []
        and len(first_stop) == 1
        and len(second_stop) == 1,
        f"sent {sent[:2]}",
    )
    fails += check(
        "pressure: resumes every paused unit once memory returns",
        sorted(sent[2:]) == [(102, SIGCONT), (103, SIGCONT)] and len(resumed) == 2,
        f"resumed {sent[2:]}",
    )
    fails += check(
        "pressure: a pause and a resume are reported with the memory that caused them",
        "paused" in first_stop[0]
        and "500 MiB" in first_stop[0]
        and "resumed" in resumed[0]
        and "4096 MiB" in resumed[0],
        f"{first_stop} {resumed}",
    )
    between: list[tuple[int, int]] = []
    fails += check(
        "pressure: NEGATIVE a host between the thresholds changes nothing (no flapping)",
        PressureGuard(
            1024,
            2560,
            reader=lambda: 1500 * MIB,
            stopper=lambda g, s: between.append((g, s)),
        ).poll(groups)
        == []
        and between == [],
        f"sent {between}",
    )
    alone: list[tuple[int, int]] = []
    single = PressureGuard(
        1024, 2560, reader=lambda: 100 * MIB, stopper=lambda g, s: alone.append((g, s))
    )
    quiet = single.poll([201]) + single.poll([201])
    fails += check(
        "pressure: NEGATIVE the last running unit is never paused",
        quiet == [] and alone == [],
        f"{quiet} {alone}",
    )
    # A unit that ended is no longer in the registry, so the survivor is never paused.
    ended: list[tuple[int, int]] = []
    shrinking = PressureGuard(
        1024, 2560, reader=lambda: 100 * MIB, stopper=lambda g, s: ended.append((g, s))
    )
    shrinking.poll([301, 302])
    shrinking.poll([301])
    fails += check(
        "pressure: a unit that ended is forgotten; the survivor keeps running",
        ended == [(302, SIGSTOP)] and shrinking.stopped == set(),
        f"{ended} {shrinking.stopped}",
    )
    exiting: list[tuple[int, int]] = []
    leaving = PressureGuard(
        1024,
        2560,
        reader=lambda: 100 * MIB,
        stopper=lambda g, s: exiting.append((g, s)),
    )
    leaving.poll([401, 402])
    leaving.resume_all()
    fails += check(
        "pressure: a guard that exits resumes what it stopped",
        exiting == [(402, SIGSTOP), (402, SIGCONT)],
        f"{exiting}",
    )

    registry = UnitRegistry(root / "registry")
    older, newer = _live_group(), _live_group()
    first = registry.register(older.pid, "build")
    registry.register(older.pid, "swarm")
    registry.register(newer.pid, "run")
    dead = _live_group()
    registry.register(dead.pid, "build")
    dead.kill()
    dead.wait()
    process_gone(dead.pid)
    live = registry.live()
    fails += check(
        "units: one live unit per group, oldest first; a dead group's entry is pruned",
        [unit.group for unit in live] == [older.pid, newer.pid]
        and not list(registry.directory.glob(f"{dead.pid}-*.json")),
        f"{[(u.group, u.kind) for u in live]}",
    )
    registry.remove(first)
    fails += check(
        "units: removing one registrant's entry keeps the group's other entry",
        [unit.group for unit in registry.live()] == [older.pid, newer.pid],
    )
    for unit in (older, newer):
        unit.kill()
        unit.wait()
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
        list(config["external_directory"].items())
        == [("*", "deny"), ("/ref/**", "allow")]
        and list(config["edit"].items()) == [("*", "allow"), ("/ref/**", "deny")],
        str(config),
    )
    opencode = BACKENDS["opencode"].command(
        Path("/j/task.md"), ["a.c"], "opencode/space-bunny-free"
    )
    pi = BACKENDS["pi"].command(
        Path("/j/task.md"), ["a.c"], "opencode/space-bunny-free"
    )
    return (
        confined
        + check(
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
        )
        + check(
            "swarm: pi argv is print-mode, sessionless, lean, with the task attached first",
            pi
            == [
                "pi",
                "-p",
                "--no-session",
                "--no-extensions",
                "--no-prompt-templates",
                "--no-themes",
                "--model",
                "opencode/space-bunny-free",
                "--",
                "@/j/task.md",
                "@a.c",
                PROMPT_ATTACHED,
            ],
            str(pi),
        )
    )


HEAVY_CLI = HERE.parent / "tools" / "heavy.py"
# A command that names its own pid and then outlives any reasonable test: the
# pid is how a kill is proven to have reached it.
SLEEPER = (
    "import os, sys, time; "
    "open(sys.argv[1], 'w').write(str(os.getpid())); "
    "sys.stdout.flush(); time.sleep(60)"
)


def _heavy(
    locks: Path,
    *argv: str,
    timeout: float = 20.0,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PY, str(HEAVY_CLI), "--lock-dir", str(locks), *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=cwd,
        env=env,
    )


def _heavy_wrapper(locks: Path, marker: Path) -> subprocess.Popen[str]:
    """Start ``heavy.py`` in a fresh session, running a sleeper that reports its pid."""
    return subprocess.Popen(
        [
            PY,
            str(HEAVY_CLI),
            "--lock-dir",
            str(locks),
            "--",
            PY,
            "-c",
            SLEEPER,
            str(marker),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _command_pid(
    marker: Path, wrapper: subprocess.Popen[str], seconds: float = 10.0
) -> int:
    """The pid the admitted command reported, or -1 if it never started."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return int(marker.read_text())
        except (FileNotFoundError, ValueError):
            pass
        if wrapper.poll() is not None:
            break
        time.sleep(0.05)
    return -1


def _marker_pid(marker: Path, seconds: float = 10.0) -> int:
    """The pid a process wrote into ``marker``, or -1 if it never did."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return int(marker.read_text())
        except (FileNotFoundError, ValueError):
            time.sleep(0.05)
    return -1


# A command that outlives any test with its whole subtree: the shell and both
# sleeps must all be gone, not only the one process heavy.py started.
TREE = "sleep 60 & sleep 60 & wait"
# The reaper, the shell and the two sleeps, all of them below the wrapper.
TREE_SIZE = 4


def _wrapper_tree(
    locks: Path, script: str, size: int
) -> tuple[subprocess.Popen[bytes], list[int]]:
    """Start ``heavy.py`` in a fresh session; return it and every pid below it."""
    wrapper = subprocess.Popen(
        [
            PY,
            str(HEAVY_CLI),
            "--lock-dir",
            str(locks),
            "--",
            "sh",
            "-c",
            script,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 15.0
    pids: list[int] = []
    while time.time() < deadline:
        pids = descendants(wrapper.pid)
        if len(pids) >= size:
            break
        if wrapper.poll() is not None:
            break
        time.sleep(0.05)
    return wrapper, pids


def _all_gone(pids: Sequence[int], seconds: float = 10.0) -> bool:
    return bool(pids) and all(process_gone(pid, seconds) for pid in pids)


def _survivors(pids: Sequence[int]) -> list[int]:
    return [pid for pid in pids if not process_gone(pid, 0.1)]


def _orphan_checks(check: Check, locks: Path, root: Path) -> int:
    """The measured orphan: a wrapper killed on its own left cmake's ninja running.

    ``PR_SET_PDEATHSIG`` reaches the one process it was set on. A build's real
    work runs in grandchildren, which that signal never touches, so the subtree
    is the unit that has to be taken down.
    """
    fails = 0
    term_wrapper, term_pids = _wrapper_tree(locks, TREE, TREE_SIZE)
    if term_pids:
        term_wrapper.send_signal(SIGTERM)
    term_wrapper.wait(timeout=15)
    fails += check(
        "heavy: SIGTERM to the wrapper takes the command's whole subtree",
        _all_gone(term_pids),
        f"wrapper exit {term_wrapper.returncode}, survivors {_survivors(term_pids)}",
    )

    kill_wrapper, kill_pids = _wrapper_tree(locks, TREE, TREE_SIZE)
    if kill_pids:
        kill_wrapper.kill()
    kill_wrapper.wait(timeout=15)
    fails += check(
        "heavy: SIGKILL to the wrapper takes the command's whole subtree",
        _all_gone(kill_pids),
        f"wrapper exit {kill_wrapper.returncode}, survivors {_survivors(kill_pids)}",
    )

    # The command finishes cleanly and leaves a daemon in a session of its own:
    # a group kill cannot reach it, so only the parent graph can.
    daemon_marker = root / "daemon.pid"
    daemon_script = (
        f"setsid sh -c 'echo $$ > {daemon_marker}; exec sleep 60' "
        f">/dev/null 2>&1 & while [ ! -s {daemon_marker} ]; do sleep 0.05; "
        "done; exit 0"
    )
    finished = _heavy(locks, "--", "sh", "-c", daemon_script)
    daemon_pid = _marker_pid(daemon_marker)
    fails += check(
        "heavy: a setsid daemon the command leaves behind is reaped",
        finished.returncode == 0 and daemon_pid > 0 and process_gone(daemon_pid, 10.0),
        f"exit {finished.returncode}, daemon pid {daemon_pid}, {finished.stderr}",
    )
    return fails


def _reaper_adoption_checks(check: Check) -> int:
    """An orphan the reaper adopts is reaped while the reaper's own child still runs.

    The measured bug: the reaper waited only for its child, so a heavy.py whose
    parent exited stayed a zombie for the rest of the worker's run.
    """
    # The subshell starts a short sleep and exits at once, so the sleep is
    # orphaned onto the reaper and ends while the long sleep still runs.
    reaper = subprocess.Popen(
        [
            PY,
            "-c",
            "import sys; sys.path.insert(0, sys.argv.pop(1));"
            "from swarmkit.reaper import main; sys.exit(main(sys.argv[1:]))",
            str(HERE.parent / "tools"),
            str(os.getpid()),
            "--",
            "sh",
            "-c",
            "(sleep 0.2 &); sleep 3",
        ]
    )
    # The short sleep has ended by now and the long one has not.
    time.sleep(1.0)
    below = descendants(reaper.pid)
    zombies = [pid for pid in below if _proc_state(pid) == "Z"]
    running = reaper.poll() is None
    reaper.wait(timeout=15)
    return check(
        "reaper: an adopted orphan is reaped while the child still runs",
        running and bool(below) and not zombies and reaper.returncode == 0,
        f"below {below}, zombies {zombies}, still running {running}, exit {reaper.returncode}",
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
        "heavy: NEGATIVE the removed --mem-mib flag is refused",
        _heavy(locks, "--mem-mib", "512", "--", PY, "-c", "pass").returncode == 2,
    )
    repo = make_repo(root / "ccache")
    nested = repo / "sub"
    nested.mkdir()
    show = (
        PY,
        "-c",
        "import os; print('BASEDIR=' + os.environ.get('CCACHE_BASEDIR', ''))",
    )
    inside = _heavy(locks, "--kind", "run", "--", *show, cwd=nested)
    # The scratch root itself sits inside a checkout; stop git's search above it.
    bare = root / "no-repo"
    bare.mkdir()
    outside = _heavy(
        locks,
        "--kind",
        "run",
        "--",
        *show,
        cwd=bare,
        env=dict(os.environ, GIT_CEILING_DIRECTORIES=str(root)),
    )
    fails += check(
        "heavy: a command in a git checkout shares ccache from the checkout's root",
        f"BASEDIR={repo.resolve()}" in inside.stdout,
        inside.stdout + inside.stderr,
    )
    fails += check(
        "heavy: NEGATIVE outside a git checkout no ccache base is invented",
        "BASEDIR=\n" in outside.stdout,
        outside.stdout + outside.stderr,
    )
    fails += check(
        "heavy: the command's unit is removed when it ends",
        _heavy(locks, "--", PY, "-c", "pass").returncode == 0
        and not list((locks / "units").glob("*.json")),
    )
    # Six builds that each sleep one second finish together: nothing queues them.
    started = time.monotonic()
    many = [
        subprocess.Popen(
            [
                PY,
                str(HEAVY_CLI),
                "--lock-dir",
                str(locks),
                "--",
                PY,
                "-c",
                "import time; time.sleep(1)",
            ]
        )
        for _ in range(6)
    ]
    codes = [child.wait(timeout=30) for child in many]
    elapsed = time.monotonic() - started
    fails += check(
        "heavy: NEGATIVE six builds at once are not queued behind each other",
        codes == [0] * 6 and elapsed < 3.0,
        f"codes {codes}, {elapsed:.1f} s",
    )

    daemon = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    _heavy(locks, "--", PY, "-c", daemon)
    fails += check(
        "heavy: a daemon left by the command does not keep its unit",
        not list((locks / "units").glob("*.json")),
    )

    # The measured orphan: a timed-out worker's whole process group is SIGKILLed, and
    # the gate the worker started must not survive inside a session of its own.
    group_marker = root / "group.pid"
    group_wrapper = _heavy_wrapper(locks, group_marker)
    group_pid = _command_pid(group_marker, group_wrapper)
    wrapper_group = os.getpgid(group_wrapper.pid) if group_pid > 0 else -1
    command_group = (
        os.getpgid(group_pid) if group_pid > 0 else -1
    )  # -1: the command never started
    registered = [
        json.loads(entry.read_text(encoding="utf-8"))
        for entry in sorted((locks / "units").glob("*.json"))
    ]
    if group_pid > 0:
        try:
            os.killpg(group_wrapper.pid, SIGKILL)
        except ProcessLookupError:
            pass
    group_wrapper.wait(timeout=10)
    fails += check(
        "heavy: the command runs in the wrapper's own process group",
        group_pid > 0 and command_group == wrapper_group,
        f"command pid {group_pid} in group {command_group}, wrapper group {wrapper_group}",
    )
    fails += check(
        "heavy: the unit registered is that live group, not a dead one",
        any(
            entry.get("group") == wrapper_group and entry.get("kind") == "build"
            for entry in registered
        ),
        f"wrapper group {wrapper_group}, entries {registered}",
    )
    fails += check(
        "heavy: killing the caller's process group kills the command too",
        group_pid > 0 and process_gone(group_pid, 5.0),
        f"command pid {group_pid}, wrapper exit {group_wrapper.returncode}",
    )

    # The other half: the wrapper killed on its own takes the command with it.
    death_marker = root / "death.pid"
    death_wrapper = _heavy_wrapper(locks, death_marker)
    death_pid = _command_pid(death_marker, death_wrapper)
    if death_pid > 0:
        try:
            death_wrapper.kill()
        except ProcessLookupError:
            pass
    death_wrapper.wait(timeout=10)
    fails += check(
        "heavy: killing the wrapper alone kills its command (parent-death signal)",
        death_pid > 0 and process_gone(death_pid, 5.0),
        f"command pid {death_pid}, wrapper exit {death_wrapper.returncode}",
    )
    return fails + _orphan_checks(check, locks, root)


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
    print(
        "swarm selftest: %s (%d check(s) failed)"
        % ("ok" if not fails else "FAIL", fails)
    )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
