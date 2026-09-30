"""The operations the CLI composes: start, ask, watch, wait, and stop.

An agent is a supervisor process plus its files under ``<state-dir>/<name>/``.
Every command here addresses it by name, refuses rather than guesses when its
state is unusable, and never matches a process by name.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import meta as meta_module
from . import views
from .config import (
    FIRST_PROMPT_TIMEOUT_SECONDS,
    POLL_SECONDS,
    TERMINATE_GRACE_SECONDS,
    PiAgentConfig,
)
from .link import ControlError, ControlLink, data_of, error_of
from .paths import AgentPaths, known_agents
from .procs import pid_alive, terminate
from .supervise import BOOTSTRAP, SupervisorSettings
from .transcript import Summary, read_events, summarize

TOOLS_DIR = Path(__file__).resolve().parent.parent
SETTLED, DEAD, TIMED_OUT = 0, 1, 2
FOLLOW_POLL_SECONDS = 0.25
# Reported as the first prompt's disposition when the agent was started without one.
IDLE = "no prompt"


class Refused(RuntimeError):
    """The request cannot be served as asked; the caller exits 2."""


@dataclass(frozen=True)
class StartSettings:
    """What ``piagent.py start`` was asked for."""

    config: PiAgentConfig
    name: str
    cwd: Path
    brief: Path | None = None
    message: str | None = None
    thinking_level: str | None = None
    session_dir: Path | None = None

    def first_prompt(self) -> str | None:
        """The opening message, or None to bring the agent up idle for later.

        Both sources at once is ambiguous and refused; neither is a deliberate
        choice to start the agent without work and steer it afterwards.
        """
        if self.brief is not None and self.message is not None:
            raise Refused("give exactly one of --brief FILE or --message TEXT")
        if self.brief is not None:
            try:
                return self.brief.expanduser().read_text(encoding="utf-8")
            except OSError as error:
                raise Refused(f"cannot read brief {self.brief}: {error}") from error
        return self.message


@dataclass(frozen=True)
class StartOutcome:
    """What a successful ``start`` reports."""

    name: str
    state_dir: Path
    supervisor_pid: int
    pi_pid: int | None
    disposition: str


def start(settings: StartSettings) -> StartOutcome:
    """Launch a detached supervisor and return once pi accepted the first prompt."""
    cwd = settings.cwd.expanduser()
    if not cwd.is_dir():
        raise Refused(f"--cwd {cwd} is not a directory")
    paths = AgentPaths(settings.config.state_dir, settings.name)
    existing = Agent(paths)
    if existing.is_alive():
        raise Refused(
            f"agent {settings.name} is already live "
            f"(supervisor pid {existing.meta_record().supervisor_pid if existing.meta_record() else '?'})"
        )
    paths.ensure()
    remove_stale_socket(paths)
    paths.first_prompt.unlink(missing_ok=True)  # never answer from a previous run
    paths.meta.unlink(missing_ok=True)  # never read the previous run's pids as this one's
    first_prompt = settings.first_prompt()
    supervisor = SupervisorSettings(
        name=settings.name,
        state_dir=str(settings.config.state_dir),
        cwd=str(cwd),
        pi_binary=settings.config.pi_binary,
        model=settings.config.model,
        thinking_level=settings.thinking_level,
        session_dir=str(settings.session_dir) if settings.session_dir else None,
        first_prompt=first_prompt,
    )
    pid = _launch_supervisor(paths, supervisor)
    answer = _await_first_prompt(paths, pid, expects_prompt=supervisor.first_prompt is not None)
    record = meta_module.read(paths.meta)
    if answer is not None and not answer.get("ok"):
        failure = str(answer.get("error") or error_of(answer.get("response") or {}))
        Agent(paths).stop()
        raise Refused(f"pi refused the first prompt: {failure}")
    if record is None:
        raise Refused(
            f"agent {settings.name} (supervisor pid {pid}) wrote no meta.json; "
            f"see {paths.supervisor_log}"
        )
    return StartOutcome(
        name=settings.name,
        state_dir=paths.directory,
        supervisor_pid=record.supervisor_pid,
        pi_pid=record.pi_pid,
        disposition=str(
            (answer or {}).get("response", {}).get("data", {}).get("disposition", IDLE)
        ),
    )


def _launch_supervisor(paths: AgentPaths, settings: SupervisorSettings) -> int:
    argv = [sys.executable, "-c", BOOTSTRAP, str(TOOLS_DIR), settings.to_json()]
    with paths.supervisor_log.open("ab", buffering=0) as log:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    return child.pid


def _await_first_prompt(
    paths: AgentPaths, pid: int, expects_prompt: bool
) -> dict[str, Any] | None:
    """Wait until the agent is ready, and for the first prompt's own answer.

    With a first prompt the socket answering ``get_state`` proves nothing --
    the prompt may still be in pi's hands -- so the supervisor's recorded
    answer is the only thing that counts. Without one, the socket answering is
    exactly the readiness signal, and the agent comes up idle.
    """
    link = ControlLink(paths.socket)
    deadline = time.time() + FIRST_PROMPT_TIMEOUT_SECONDS
    while time.time() < deadline:
        if expects_prompt and paths.first_prompt.is_file():
            try:
                return json.loads(paths.first_prompt.read_text(encoding="utf-8"))
            except ValueError:
                time.sleep(POLL_SECONDS)
                continue
        if not expects_prompt and link.probe():
            return None
        record = meta_module.read(paths.meta)
        if record is not None and not pid_alive(record.supervisor_pid):
            raise Refused(
                f"the supervisor for {paths.name} exited with code {record.exit_code}: "
                f"{record.error or 'see ' + str(paths.supervisor_log)}"
            )
        if record is None and not pid_alive(pid):
            raise Refused(
                f"the supervisor for {paths.name} (pid {pid}) died before it could start; "
                f"see {paths.supervisor_log}"
            )
        time.sleep(POLL_SECONDS)
    waiting_for = "the first prompt's answer" if expects_prompt else "the agent to come up"
    raise Refused(
        f"no {waiting_for} for {paths.name} within {FIRST_PROMPT_TIMEOUT_SECONDS:g}s; "
        f"see {paths.supervisor_log} and {paths.stderr}"
    )


def remove_stale_socket(paths: AgentPaths) -> bool:
    """Unlink a control socket no supervisor is answering on."""
    if not paths.socket.exists():
        return False
    if ControlLink(paths.socket, timeout=1.0).probe():
        return False
    paths.socket.unlink(missing_ok=True)
    return True


class Agent:
    """One named agent: its files, its liveness, and the commands it accepts."""

    def __init__(self, paths: AgentPaths) -> None:
        self.paths = paths

    @property
    def name(self) -> str:
        return self.paths.name

    def meta_record(self) -> meta_module.AgentMeta | None:
        return meta_module.read(self.paths.meta)

    def require_meta(self) -> meta_module.AgentMeta:
        record = self.meta_record()
        if record is None:
            raise Refused(
                f"no agent named {self.name} under {self.paths.root}"
                if not self.paths.directory.is_dir()
                else f"agent {self.name} has no readable meta.json in {self.paths.directory}"
            )
        return record

    def is_alive(self) -> bool:
        """Live means the supervisor pid is running *and* its socket answers."""
        record = self.meta_record()
        if record is None or not pid_alive(record.supervisor_pid):
            return False
        return ControlLink(self.paths.socket, timeout=5.0).probe()

    def supervisor_alive(self) -> bool:
        """Cheap liveness: the recorded supervisor pid, with no round trip."""
        record = self.meta_record()
        return record is not None and pid_alive(record.supervisor_pid)

    def ask(self, command: str, **fields: Any) -> dict[str, Any]:
        """Send one RPC command through the supervisor; raise if it cannot."""
        self.require_meta()
        if not self.is_alive():
            raise Refused(f"agent {self.name} is not live; see `piagent.py status {self.name}`")
        try:
            return ControlLink(self.paths.socket).request(command, **fields)
        except ControlError as error:
            raise Refused(str(error)) from error

    # -- observation -------------------------------------------------------
    def events(self) -> list[tuple[bytes, Any | None]]:
        return read_events(self.paths.events)

    def summary(self) -> Summary:
        return summarize([parsed for _, parsed in self.events()])

    def state(self) -> dict[str, Any] | None:
        """pi's ``get_state``, or None when the agent cannot answer."""
        return self._ask_data("get_state") if self.is_alive() else None

    def stats(self) -> dict[str, Any] | None:
        """Token and context accounting, or None when pi will not say."""
        return self._ask_data("get_session_stats") if self.is_alive() else None

    def _ask_data(self, command: str) -> dict[str, Any] | None:
        try:
            response = self.ask(command)
        except Refused:
            return None
        return data_of(response) if response.get("success") is True else None

    def stderr_tail(self, lines: int = 3) -> list[str]:
        if not self.paths.stderr.is_file():
            return []
        text = self.paths.stderr.read_text(encoding="utf-8", errors="replace")
        return [line for line in text.splitlines() if line.strip()][-lines:]

    def status_lines(self) -> list[str]:
        record = self.require_meta()
        summary = self.summary()
        alive = self.is_alive()
        state = self._ask_data("get_state") if alive else None
        stats = self._ask_data("get_session_stats") if alive else None
        return views.status_block(
            name=self.name,
            alive=alive,
            supervisor_pid=record.supervisor_pid,
            pi_pid=record.pi_pid,
            cwd=record.cwd,
            model=record.model,
            streaming=(state or {}).get("isStreaming"),
            summary=summary,
            elapsed=record.elapsed,
            state_data=state,
            stats=stats,
            exit_code=record.exit_code,
            error=record.error,
            stderr_lines=self.stderr_tail(),
        )

    def tail_lines(self, limit: int) -> list[str]:
        return views.tail_lines(self.events(), limit)

    def follow(self) -> Iterator[str]:
        """Yield new transcript lines as they land, until the agent settles or dies."""
        seen = 0
        while True:
            events = self.events()
            for line in views.tail_lines(events[seen:], 0):
                yield line
            seen = len(events)
            if not self.supervisor_alive():
                yield "-- agent is gone; stopping follow"
                return
            summary = summarize([parsed for _, parsed in events])
            if summary.settled and not summary.open_run:
                yield "-- agent settled"
                return
            time.sleep(FOLLOW_POLL_SECONDS)

    # -- control -----------------------------------------------------------
    def send(self, text: str, follow_up: bool = False) -> str:
        """Prompt when idle, steer while streaming, or force a follow-up."""
        if not text.strip():
            raise Refused("refusing to send an empty message")
        state = self.state()
        if follow_up:
            command = "follow_up"
        elif state is not None and state.get("isStreaming"):
            command = "steer"
        else:
            command = "prompt"
        response = self.ask(command, message=text)
        if response.get("success") is not True:
            raise Refused(f"pi rejected {command}: {error_of(response)}")
        disposition = data_of(response).get("disposition", "accepted")
        return f"{command} ({disposition})"

    def abort(self) -> str:
        response = self.ask("abort")
        if response.get("success") is not True:
            raise Refused(f"pi rejected abort: {error_of(response)}")
        return "abort accepted; the agent is still alive"

    def wait(self, timeout: float) -> tuple[int, str]:
        """Block until the agent settles; returns an exit code and final text."""
        deadline = time.time() + timeout
        while True:
            summary = self.summary()
            if summary.settled and not summary.open_run:
                return SETTLED, self.final_text(summary)
            if not self.supervisor_alive():
                return DEAD, summary.last_assistant_text
            if time.time() >= deadline:
                return TIMED_OUT, summary.last_assistant_text
            time.sleep(POLL_SECONDS)

    def final_text(self, summary: Summary | None = None) -> str:
        """The last assistant message, from pi when it will answer."""
        if self.is_alive():
            try:
                response = self.ask("get_last_assistant_text")
                if response.get("success") is True:
                    text = data_of(response).get("text")
                    if isinstance(text, str) and text:
                        return text
            except Refused:
                pass
        return (summary or self.summary()).last_assistant_text

    def stop(self) -> dict[str, Any]:
        """Abort the run, then end the supervisor and pi by pid. Logs are kept."""
        record = self.require_meta()
        aborted = False
        if self.is_alive():
            try:
                self.abort()
                aborted = True
            except Refused:
                aborted = False
        terminate(record.supervisor_pid, TERMINATE_GRACE_SECONDS)
        terminate(record.pi_pid, TERMINATE_GRACE_SECONDS)
        self.paths.socket.unlink(missing_ok=True)
        return {
            "aborted": aborted,
            "supervisor_gone": not pid_alive(record.supervisor_pid),
            "pi_gone": not pid_alive(record.pi_pid),
            "directory": self.paths.directory,
        }


def agent(config: PiAgentConfig, name: str) -> Agent:
    """The named agent under the configured state directory."""
    return Agent(AgentPaths(config.state_dir, name))


def list_agents(config: PiAgentConfig) -> list[views.AgentRow]:
    """Every agent in the state dir, with stale sockets cleaned as we go."""
    rows: list[views.AgentRow] = []
    for paths in known_agents(config.state_dir):
        record = meta_module.read(paths.meta)
        if record is None:
            continue
        target = Agent(paths)
        alive = target.is_alive()
        if not alive:
            remove_stale_socket(paths)
        state = target.state() if alive else None
        rows.append(
            views.AgentRow(
                name=paths.name,
                alive=alive,
                activity="streaming" if (state or {}).get("isStreaming") else "idle",
                cwd=record.cwd,
                age=record.elapsed,
            )
        )
    return rows
