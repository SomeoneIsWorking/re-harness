#!/usr/bin/env python3
"""Positive and negative controls for tools/piagent.py, driven through its shipping modules.

A fake pi (``piagent_fake_pi.py``) stands in for the real RPC agent so every
disposition -- streaming, steering, following up, aborting, dying -- is produced
on demand. Each check states the answer it must get; the negatives state the
answer it must NOT get, because a supervisor that reports "fine" for an agent it
never reached is worse than no tool at all.

    python3 tests/piagent_checks.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE_PI = HERE / "piagent_fake_pi.py"
CLI = HERE.parent / "tools" / "piagent.py"
PY = sys.executable
sys.path.insert(0, str(HERE.parent / "tools"))

from piagentkit import framing
from piagentkit.control import DEAD, SETTLED, TIMED_OUT, Agent
from piagentkit.paths import AgentPaths, NameRefused

Check = Callable[..., int]

# U+2028 is legal inside a JSON string, and a generic line reader treats it as
# a record boundary. Every record carrying it proves the framing rule.
PARAGRAPH_SEPARATOR = "before after"


def fake_pi(*options: str) -> str:
    """The fake pi as one ``--pi-binary`` value."""
    return " ".join([PY, str(FAKE_PI), *options])


def run_cli(root: Path, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Invoke the shipping CLI exactly as an operator would."""
    return subprocess.run(
        [PY, str(CLI), "--state-dir", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def wait_for(predicate: Callable[[], bool], seconds: float = 30.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def observe(target: Agent, *needles: str, seconds: float = 30.0) -> set[str]:
    """Poll a live agent's status and collect which of ``needles`` it ever showed.

    One poll loop, so the observations do not depend on the order checks happen
    to run in: a tool that is only "current" mid-run must be looked for while
    the run is in flight.
    """
    seen: set[str] = set()
    deadline = time.time() + seconds
    while time.time() < deadline and not set(needles) <= seen:
        block = "\n".join(target.status_lines())
        seen.update(needle for needle in needles if needle in block)
        if len(seen) < len(needles):
            time.sleep(0.05)
    return seen


def start_agent(root: Path, name: str, *options: str, message: str = "do the thing") -> Agent:
    """Start an agent through the CLI and hand back its handle."""
    result = run_cli(
        root, "start", name, "--cwd", str(root), "--message", message,
        "--pi-binary", fake_pi(*options),
    )
    if result.returncode != 0:
        raise AssertionError(f"start {name} failed ({result.returncode}):\n{result.stdout}{result.stderr}")
    return Agent(AgentPaths(root, name))


def io_stream(data: bytes, chunk: int = 0):
    """A byte stream whose reads are bounded, like a real pipe."""

    position = 0

    def read(size: int) -> bytes:
        nonlocal position
        take = min(size if chunk == 0 else chunk, len(data) - position)
        piece = data[position : position + take]
        position += take
        return piece

    class Stream:
        read1 = staticmethod(read)

    return Stream()


def alive(pid: int | None) -> bool:
    """True unless the pid is gone or a reaped zombie."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True
    return stat.rsplit(")", 1)[-1].split()[0] != "Z"


def run_checks(check: Check, scratch: str) -> int:
    """Every group, each in its own temporary state directory."""
    fails = _framing_checks(check)
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _lifecycle_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _disposition_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _dead_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _unicode_checks(check, Path(tmp))
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        fails += _refusal_checks(check, Path(tmp))
    return fails


def _framing_checks(check: Check) -> int:
    """The framing rule, proved both ways: LF splits, U+2028 does not."""
    fails = 0
    record = framing.encode_record({"type": "message_update", "text": PARAGRAPH_SEPARATOR})
    split = list(framing.read_records(io_stream(record + record)))
    fails += check(
        "piagent: a record containing U+2028 is one record, not two",
        len(split) == 2
        and all(parsed is not None for _, parsed in split)
        and split[0][1]["text"] == PARAGRAPH_SEPARATOR,
        f"{len(split)} record(s): {[parsed for _, parsed in split]}",
    )
    # The negative control: the reader this must not use really does break here.
    pieces = record.decode("utf-8").splitlines()
    try:
        framing.decode_record(pieces[0].encode("utf-8"))
        corrupted = ""
    except ValueError as error:
        corrupted = str(error)
    fails += check(
        "piagent: NEGATIVE a Unicode line reader really would corrupt that record",
        len(pieces) > 1 and bool(corrupted),
        f"splitlines produced {len(pieces)} pieces; first piece: {corrupted or 'parsed anyway'}",
    )
    chunked = io_stream(
        b"".join(framing.encode_record({"type": "x", "n": n}) for n in range(5)), chunk=3
    )
    recovered = [parsed["n"] for _, parsed in framing.read_records(chunked) if parsed]
    fails += check(
        "piagent: records survive a reader that hands over three bytes at a time",
        recovered == [0, 1, 2, 3, 4],
        repr(recovered),
    )
    crlf = io_stream(framing.encode_record({"type": "x"})[:-1] + b"\r\n")
    fails += check(
        "piagent: a CRLF record is accepted, its carriage return stripped",
        [parsed for _, parsed in framing.read_records(crlf)] == [{"type": "x"}],
    )
    return fails


def _lifecycle_checks(check: Check, root: Path) -> int:
    """start, status, tail, wait, stop, and the refusals around them."""
    fails = 0
    target = start_agent(root, "alpha", "--slow", "1.0")
    paths = target.paths
    fails += check(
        "piagent: start leaves a supervisor, a meta file, and a private socket",
        paths.meta.is_file() and paths.socket.exists() and paths.supervisor_log.is_file(),
        str(paths.directory),
    )
    # One call arrives twice on a real stream (toolcall_end, then the execution
    # events); a tool must be one record, and unfinished while it is running.
    needles = ("activity  streaming", "activity  idle", "edit (current)", "edit (last)")
    seen = observe(target, *needles)
    fails += check(
        "piagent: a live agent's status shows streaming then idle, and a running tool",
        set(needles) <= seen,
        f"never saw: {sorted(set(needles) - seen)}\n" + "\n".join(target.status_lines()),
    )
    fails += check(
        "piagent: status reports the run, the last tool, and the edited file",
        wait_for(lambda: "edit" in "\n".join(target.status_lines()))
        and "notes.md" in "\n".join(target.status_lines())
        and "1 run(s)" in "\n".join(target.status_lines()),
        "\n".join(target.status_lines()),
    )
    summary = target.summary()
    fails += check(
        "piagent: a call announced then executed is one tool record, finished",
        len(summary.tool_calls) == 1
        and summary.current_tool is None
        and summary.last_tool is not None
        and summary.last_tool.finished,
        repr(summary.tool_calls),
    )
    fails += check(
        "piagent: status reports token and context usage while pi will answer",
        "context 6.0%" in "\n".join(target.status_lines()),
        "\n".join(target.status_lines()),
    )
    duplicate = run_cli(root, "start", "alpha", "--cwd", str(root), "--message", "again")
    fails += check(
        "piagent: NEGATIVE starting a live name is refused",
        duplicate.returncode == 2 and "already live" in duplicate.stderr,
        duplicate.stderr,
    )
    tail = run_cli(root, "tail", "alpha", "-n", "60")
    fails += check(
        "piagent: tail shows the tool call, its result, and the settle",
        "tool edit" in tail.stdout
        and "notes.md" in tail.stdout
        and "edited notes.md" in tail.stdout
        and "agent_settled" in tail.stdout,
        tail.stdout,
    )
    code, text = target.wait(30.0)
    fails += check(
        "piagent: wait exits 0 on agent_settled and prints the final message",
        code == SETTLED and "working: noted" in text,
        f"code={code} text={text!r}",
    )
    listed = run_cli(root, "list")
    fails += check(
        "piagent: list shows the agent as alive, idle, with its cwd and age",
        "alpha" in listed.stdout
        and "alive" in listed.stdout
        and "idle" in listed.stdout
        and str(root) in listed.stdout,
        listed.stdout,
    )
    followed = run_cli(root, "tail", "alpha", "--follow")
    fails += check(
        "piagent: tail --follow on a settled agent ends with a settle marker",
        followed.returncode == 0 and "agent settled" in followed.stdout,
        followed.stdout,
    )
    record = target.meta_record()
    stopped = run_cli(root, "stop", "alpha")
    after = "\n".join(target.status_lines())
    fails += check(
        "piagent: stop ends the supervisor and pi by pid, and keeps the logs",
        stopped.returncode == 0
        and not alive(record.supervisor_pid)
        and not alive(record.pi_pid)
        and paths.events.is_file()
        and not paths.socket.exists()
        and "dead" in after
        and "stopped by the operator" in after,
        f"{stopped.stdout}{stopped.stderr}\n{after}",
    )
    again = run_cli(root, "start", "alpha", "--cwd", str(root), "--message", "second run")
    fails += check(
        "piagent: the same name can be started again after stop",
        again.returncode == 0 and "started alpha" in again.stdout,
        f"{again.stdout}{again.stderr}",
    )
    run_cli(root, "stop", "alpha")

    for command, arguments in (
        ("status", ()),
        ("send", ("say something",)),
        ("stop", ()),
        ("wait", ()),
    ):
        missing = run_cli(root, command, "ghost", *arguments)
        fails += check(
            f"piagent: NEGATIVE {command} on an agent that never existed is refused",
            missing.returncode == 2 and "no agent named" in missing.stderr,
            missing.stderr,
        )
    empty = run_cli(root, "--state-dir", str(root / "unused"), "list")
    fails += check(
        "piagent: list of an empty state dir says it is empty",
        "0 agent(s)" in empty.stdout,
        empty.stdout,
    )
    nothing = run_cli(root, "--state-dir", str(root / "never"), "list")
    fails += check(
        "piagent: NEGATIVE list never invents an agent in a state dir that does not exist",
        "0 agent(s)" in nothing.stdout and "never" in nothing.stdout,
        nothing.stdout,
    )
    return fails


def _disposition_checks(check: Check, root: Path) -> int:
    """Prompt while idle, steer while streaming, follow-up, abort, and timeout."""
    fails = 0
    target = start_agent(root, "beta", "--slow", "1.5")
    fails += check(
        "piagent: the agent really is streaming before anything is steered at it",
        wait_for(lambda: (target.state() or {}).get("isStreaming") is True),
        json.dumps(target.state()),
    )
    steered = run_cli(root, "send", "beta", "change of plan")
    fails += check(
        "piagent: send while streaming uses steer",
        steered.returncode == 0 and "steer (queued)" in steered.stdout,
        f"{steered.stdout}{steered.stderr}",
    )
    follow = run_cli(root, "send", "beta", "and then summarize", "--follow-up")
    fails += check(
        "piagent: --follow-up uses follow_up even while streaming",
        follow.returncode == 0 and "follow_up (queued)" in follow.stdout,
        f"{follow.stdout}{follow.stderr}",
    )
    code, _ = target.wait(90.0)
    status = "\n".join(target.status_lines())
    fails += check(
        "piagent: wait settles only after the queued work ran, not after the first turn",
        code == SETTLED and "3 run(s)" in status,
        status,
    )
    idle = run_cli(root, "send", "beta", "fresh work")
    fails += check(
        "piagent: send while idle uses prompt",
        idle.returncode == 0 and "prompt (started)" in idle.stdout,
        f"{idle.stdout}{idle.stderr}",
    )
    empty = run_cli(root, "send", "beta", "   ")
    fails += check(
        "piagent: NEGATIVE an empty message is refused",
        empty.returncode == 2 and "empty message" in empty.stderr,
        empty.stderr,
    )
    aborted = run_cli(root, "abort", "beta")
    fails += check(
        "piagent: abort stops the run and leaves the agent alive",
        aborted.returncode == 0 and "still alive" in aborted.stdout and target.is_alive(),
        f"{aborted.stdout}{aborted.stderr}",
    )
    run_cli(root, "stop", "beta")

    slow = start_agent(root, "gamma", "--slow", "30")
    started = time.time()
    code, _ = slow.wait(1.0)
    elapsed = time.time() - started
    fails += check(
        "piagent: wait exits 2 on timeout, and honors the deadline it was given",
        code == TIMED_OUT and elapsed < 20,
        f"code={code} after {elapsed:.1f}s",
    )
    run_cli(root, "stop", "gamma")
    return fails


def _dead_checks(check: Check, root: Path) -> int:
    """A pi that dies, and a socket its supervisor left behind."""
    fails = 0
    started = run_cli(
        root, "start", "delta", "--cwd", str(root), "--message", "hello",
        "--pi-binary", fake_pi("--die-code", "3"),
    )
    fails += check(
        "piagent: start returns once the first prompt was accepted, before the agent dies",
        started.returncode == 0,
        f"{started.stdout}{started.stderr}",
    )
    paths = AgentPaths(root, "delta")
    target = Agent(paths)
    fails += check(
        "piagent: status of a dead pi shows its exit code",
        wait_for(lambda: "dead  exit 3" in "\n".join(target.status_lines())),
        "\n".join(target.status_lines()),
    )
    code, _ = target.wait(10.0)
    fails += check(
        "piagent: wait on a dead agent exits 1, not 0",
        code == DEAD,
        f"code={code}",
    )
    refused = run_cli(root, "send", "delta", "anything")
    fails += check(
        "piagent: NEGATIVE sending to a dead agent is refused, not silently dropped",
        refused.returncode == 2 and "not live" in refused.stderr,
        refused.stderr,
    )
    listed = run_cli(root, "list")
    fails += check(
        "piagent: list reports the dead agent as dead",
        "delta" in listed.stdout and "dead" in listed.stdout,
        listed.stdout,
    )
    paths.socket.parent.mkdir(parents=True, exist_ok=True)
    paths.socket.write_bytes(b"")
    restart = run_cli(
        root, "start", "delta", "--cwd", str(root), "--message", "hello again",
        "--pi-binary", fake_pi(),
    )
    fails += check(
        "piagent: a stale socket from a crashed supervisor is cleaned, not inherited",
        restart.returncode == 0 and Agent(paths).is_alive(),
        f"{restart.stdout}{restart.stderr}",
    )
    run_cli(root, "stop", "delta")
    return fails


def _unicode_checks(check: Check, root: Path) -> int:
    """A prompt containing U+2028 must survive the whole round trip."""
    fails = 0
    target = start_agent(root, "epsilon", message=f"report {PARAGRAPH_SEPARATOR} please")
    code, _ = target.wait(30.0)
    events = target.paths.events.read_bytes()
    status = "\n".join(target.status_lines())
    tail = "\n".join(target.tail_lines(200))
    intact = [parsed for _, parsed in framing.read_records(io_stream(events))]
    fails += check(
        "piagent: a U+2028 prompt is recorded as whole records, none malformed",
        code == SETTLED
        and bool(events)
        and all(parsed is not None for parsed in intact),
        f"{len(intact)} record(s), {sum(1 for item in intact if item is None)} malformed",
    )
    fails += check(
        "piagent: the U+2028 text reached pi whole (the fake echoes the prompt back)",
        any(
            isinstance(item, dict)
            and PARAGRAPH_SEPARATOR in json.dumps(item, ensure_ascii=False)
            for item in intact
        ),
        tail,
    )
    fails += check(
        "piagent: status and tail report no framing damage",
        "malformed" not in status and "malformed" not in tail,
        status,
    )
    run_cli(root, "stop", "epsilon")
    return fails


def _refusal_checks(check: Check, root: Path) -> int:
    """The inputs a supervisor must refuse before it launches anything."""
    fails = 0
    brief = root / "brief.md"
    brief.write_text("read the brief\n", encoding="utf-8")
    both = run_cli(
        root, "start", "zeta", "--cwd", str(root),
        "--message", "text", "--brief", str(brief),
    )
    fails += check(
        "piagent: NEGATIVE both --brief and --message is refused",
        both.returncode == 2 and "exactly one" in both.stderr,
        both.stderr,
    )
    neither = run_cli(root, "start", "eta", "--cwd", str(root),
                      "--pi-binary", fake_pi())
    fails += check(
        "piagent: an agent with no first prompt comes up idle and ready to be sent",
        neither.returncode == 0
        and "no first prompt" in neither.stdout
        and Agent(AgentPaths(root, "eta")).state() is not None
        and (Agent(AgentPaths(root, "eta")).state() or {}).get("isStreaming") is False,
        f"{neither.stdout}{neither.stderr}",
    )
    sent = run_cli(root, "send", "eta", "first real work")
    fails += check(
        "piagent: that idle agent accepts a prompt as a prompt",
        sent.returncode == 0 and "prompt (started)" in sent.stdout,
        f"{sent.stdout}{sent.stderr}",
    )
    run_cli(root, "stop", "eta")
    unreadable = run_cli(
        root, "start", "zeta", "--cwd", str(root), "--brief", str(root / "absent.md")
    )
    fails += check(
        "piagent: NEGATIVE an unreadable brief is refused",
        unreadable.returncode == 2 and "cannot read brief" in unreadable.stderr,
        unreadable.stderr,
    )
    bad_cwd = run_cli(root, "start", "zeta", "--cwd", str(root / "absent"), "--message", "hi")
    fails += check(
        "piagent: NEGATIVE a --cwd that is not a directory is refused",
        bad_cwd.returncode == 2 and "not a directory" in bad_cwd.stderr,
        bad_cwd.stderr,
    )
    bad_name = run_cli(root, "status", "../escape")
    fails += check(
        "piagent: NEGATIVE a name that could escape the state dir is refused",
        bad_name.returncode == 2 and "must match" in bad_name.stderr,
        bad_name.stderr,
    )
    try:
        AgentPaths(root, "ok/../..")
    except NameRefused as error:
        refused = str(error)
    else:
        refused = ""
    fails += check(
        "piagent: NEGATIVE a traversing name cannot become a directory",
        "must match" in refused,
        refused,
    )
    return fails


def main() -> int:
    scratch = HERE.parent / "scratch" / "tests"
    scratch.mkdir(parents=True, exist_ok=True)

    def report(name: str, ok: bool, detail: str = "") -> int:
        print("  %-64s %s" % (name, "ok" if ok else "FAIL"))
        if not ok and detail:
            print("      " + detail.strip().replace("\n", "\n      ")[:800])
        return 0 if ok else 1

    fails = run_checks(report, str(scratch))
    print("piagent checks: %s (%d check(s) failed)" % ("FAILED" if fails else "PASSED", fails))
    return fails


if __name__ == "__main__":
    sys.exit(main())
