"""The supervisor: one process per agent that owns pi's stdin and stdout.

Started detached by ``piagent.py start``, it appends every stdout record
verbatim to ``events.jsonl``, keeps pi's stderr in ``stderr.log``, records the
run in ``meta.json``, and serves ``ctl.sock`` so clients can send one RPC command
per connection. Clients never touch pi directly, so only this process can
correlate a command id with its response.

Run as a module entry point:

    python3 -c "<bootstrap>" '<json settings>'
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import meta as meta_module
from .config import POLL_SECONDS, RPC_TIMEOUT_SECONDS, TERMINATE_GRACE_SECONDS
from .framing import encode_record, iter_records
from .paths import CONTROL_SOCKET_MODE, AgentPaths
from .procs import terminate

ACCEPT_TIMEOUT_SECONDS = 0.5
LAUNCH_FAILURE_EXIT = 127
BOOTSTRAP = (
    "import sys; sys.path.insert(0, sys.argv.pop(1));"
    " from piagentkit.supervise import main; main()"
)


@dataclass(frozen=True)
class SupervisorSettings:
    """Everything the supervisor needs, passed as one JSON object on argv."""

    name: str
    state_dir: str
    cwd: str
    pi_binary: str
    model: str | None
    thinking_level: str | None
    session_dir: str | None
    first_prompt: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "state_dir": self.state_dir,
                "cwd": self.cwd,
                "pi_binary": self.pi_binary,
                "model": self.model,
                "thinking_level": self.thinking_level,
                "session_dir": self.session_dir,
                "first_prompt": self.first_prompt,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> "SupervisorSettings":
        data = json.loads(text)
        return cls(
            name=data["name"],
            state_dir=data["state_dir"],
            cwd=data["cwd"],
            pi_binary=data["pi_binary"],
            model=data.get("model"),
            thinking_level=data.get("thinking_level"),
            session_dir=data.get("session_dir"),
            first_prompt=data.get("first_prompt"),
        )

    def command(self) -> list[str]:
        """The pi argv this supervisor owns.

        ``pi_binary`` may carry fixed leading arguments (``--pi-binary
        '/path/to/fake pi --slow 1'``), split the way a shell would.
        """
        argv = shlex.split(self.pi_binary) + ["--mode", "rpc"]
        if self.model:
            argv += ["--model", self.model]
        if self.thinking_level:
            argv += ["--thinking", self.thinking_level]
        if self.session_dir:
            argv += ["--session-dir", self.session_dir]
        return argv


class Supervisor:
    """Owns one pi process and the control socket in front of it."""

    def __init__(self, settings: SupervisorSettings) -> None:
        self._settings = settings
        self._paths = AgentPaths(Path(settings.state_dir), settings.name)
        self._child: subprocess.Popen | None = None
        self._stdin_lock = threading.Lock()
        self._responses: dict[str, queue.Queue] = {}
        self._responses_lock = threading.Lock()
        self._ids = 0
        self._stdout_done = threading.Event()
        self._stopping = threading.Event()
        self._server: socket.socket | None = None
        self._exit_code: int | None = None
        self._log = self._paths.stderr.open("ab", buffering=0)

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> int:
        self._paths.ensure()
        self._install_signal_handlers()
        self._bind_socket()
        record = meta_module.AgentMeta(
            name=self._settings.name,
            cwd=self._settings.cwd,
            model=self._settings.model,
            started_at=time.time(),
            supervisor_pid=os.getpid(),
            pi_binary=self._settings.pi_binary,
            thinking_level=self._settings.thinking_level,
            session_dir=self._settings.session_dir,
            argv=self._settings.command(),
        )
        record.write(self._paths.meta)
        if not self._spawn():
            return self._finish(LAUNCH_FAILURE_EXIT)
        threading.Thread(target=self._pump_stdout, name="pi-stdout", daemon=True).start()
        if self._settings.first_prompt is not None:
            self._send_first_prompt()
        while not self._stdout_done.wait(0.2):
            if self._stopping.is_set():
                break
        if self._stopping.is_set():
            self._close_child()
        return self._finish(self._exit_code)

    def _spawn(self) -> bool:
        argv = self._settings.command()
        try:
            self._child = subprocess.Popen(
                argv,
                cwd=self._settings.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log,
                start_new_session=True,
            )
        except OSError as error:
            message = f"could not launch {argv[0]!r}: {error}"
            self._note(message)
            self._write_meta_dead(None, message)
            if self._settings.first_prompt is not None:
                self._write_first_prompt({"ok": False, "error": message})
            return False
        record = meta_module.read(self._paths.meta)
        if record is not None:
            record.pi_pid = self._child.pid
            record.write(self._paths.meta)
        return True

    def _install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            self._stopping.set()

        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, stop)

    def _note(self, message: str) -> None:
        self._log.write(f"piagent: {message}\n".encode("utf-8"))

    def _write_meta_dead(self, exit_code: int | None, error: str | None) -> None:
        record = meta_module.read(self._paths.meta)
        if record is None:
            return
        record.mark_dead(exit_code, error)
        record.write(self._paths.meta)

    def _finish(self, exit_code: int | None) -> int:
        if self._child is not None and self._child.poll() is None:
            self._close_child()
            exit_code = self._child.returncode
        self._exit_code = self._child.returncode if self._child is not None else exit_code
        stopped = self._stopping.is_set()
        self._write_meta_dead(self._exit_code, "stopped by the operator" if stopped else None)
        if self._server is not None:
            self._server.close()
        try:
            self._paths.socket.unlink()
        except FileNotFoundError:
            pass
        self._log.close()
        return self._exit_code if self._exit_code is not None else 0

    def _close_child(self) -> None:
        """End pi by the pid this process started, then reap it."""
        if self._child is None or self._child.poll() is not None:
            return
        self._note(f"terminating pi pid {self._child.pid}")
        try:
            if self._child.stdin is not None:
                self._child.stdin.close()
        except OSError:
            pass
        terminate(self._child.pid, TERMINATE_GRACE_SECONDS)
        try:
            self._child.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._note("pi did not exit; supervisor exiting anyway")

    # -- stdout pump -------------------------------------------------------
    def _pump_stdout(self) -> None:
        """Append every record verbatim, then route responses to their waiters.

        The log is unbuffered: an operator running ``tail --follow`` against
        another process must see each record as it lands, not when a buffer
        happens to fill.
        """
        assert self._child is not None and self._child.stdout is not None
        with self._paths.events.open("wb", buffering=0) as events:
            for record in iter_records(self._child.stdout.read1):
                events.write(record + b"\n")
                self._dispatch(record)
        self._stdout_done.set()

    def _dispatch(self, record: bytes) -> None:
        try:
            parsed = json.loads(record.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._note(f"dropped a record that is not JSON: {record[:120]!r}")
            return
        if not isinstance(parsed, dict) or parsed.get("type") != "response":
            return
        identifier = parsed.get("id")
        if not isinstance(identifier, str):
            return
        with self._responses_lock:
            waiter = self._responses.get(identifier)
        if waiter is not None:
            waiter.put(parsed)

    # -- control socket ----------------------------------------------------
    def _bind_socket(self) -> None:
        if self._paths.socket.exists():
            self._paths.socket.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self._paths.socket))
        os.chmod(self._paths.socket, CONTROL_SOCKET_MODE)
        server.listen(16)
        server.settimeout(ACCEPT_TIMEOUT_SECONDS)
        self._server = server
        threading.Thread(target=self._serve, name="ctl-sock", daemon=True).start()

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stopping.is_set():
            try:
                connection, _ = self._server.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            threading.Thread(
                target=self._serve_one, args=(connection,), name="ctl-conn", daemon=True
            ).start()

    def _serve_one(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(RPC_TIMEOUT_SECONDS)
            try:
                request = next(iter(iter_records(lambda size: connection.recv(size))), None)
            except (OSError, ValueError) as error:
                self._reply(connection, {"success": False, "error": f"unreadable request: {error}"})
                return
            if request is None:
                self._reply(connection, {"success": False, "error": "no request"})
                return
            try:
                parsed = json.loads(request.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as error:
                self._reply(connection, {"success": False, "error": f"request is not JSON: {error}"})
                return
            if not isinstance(parsed, dict) or "type" not in parsed:
                self._reply(
                    connection, {"success": False, "error": "request needs a string \"type\""}
                )
                return
            self._reply(connection, self.forward(parsed))

    def _reply(self, connection: socket.socket, response: dict[str, Any]) -> None:
        try:
            connection.sendall(encode_record(response))
        except OSError:
            pass

    def forward(self, request: dict[str, Any]) -> dict[str, Any]:
        """Give one command a unique id, send it to pi, and await its response."""
        with self._responses_lock:
            self._ids += 1
            identifier = f"ctl-{os.getpid()}-{self._ids}"
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self._responses_lock:
            self._responses[identifier] = waiter
        record = {"id": identifier, **request}
        try:
            self._send_to_pi(record)
        except OSError as error:
            self._forget(identifier)
            return {"success": False, "error": f"pi is not accepting commands: {error}"}
        try:
            return self._await_response(identifier, waiter)
        finally:
            self._forget(identifier)

    def _send_to_pi(self, record: dict[str, Any]) -> None:
        if self._child is None or self._child.stdin is None:
            raise OSError("pi was never started")
        with self._stdin_lock:
            self._child.stdin.write(encode_record(record))
            self._child.stdin.flush()

    def _await_response(self, identifier: str, waiter: queue.Queue) -> dict[str, Any]:
        deadline = time.time() + RPC_TIMEOUT_SECONDS
        while time.time() < deadline:
            if not waiter.empty():
                return waiter.get()
            if self._child is not None and self._child.poll() is not None:
                return {
                    "id": identifier,
                    "type": "response",
                    "success": False,
                    "error": f"pi exited with code {self._child.returncode} before responding",
                }
            if self._stopping.is_set():
                break
            time.sleep(POLL_SECONDS)
        return {
            "id": identifier,
            "type": "response",
            "success": False,
            "error": f"no response from pi within {RPC_TIMEOUT_SECONDS:g}s",
        }

    def _forget(self, identifier: str) -> None:
        with self._responses_lock:
            self._responses.pop(identifier, None)

    # -- first prompt ------------------------------------------------------
    def _send_first_prompt(self) -> None:
        response = self.forward(
            {"type": "prompt", "message": self._settings.first_prompt or ""}
        )
        self._write_first_prompt({"ok": response.get("success") is True, "response": response})

    def _write_first_prompt(self, payload: dict[str, Any]) -> None:
        temporary = self._paths.first_prompt.with_name(
            self._paths.first_prompt.name + f".{os.getpid()}.tmp"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self._paths.first_prompt)


def main() -> int:
    """Entry point for the detached supervisor process."""
    if len(sys.argv) < 2:
        sys.exit("piagent supervisor: expected one JSON settings argument")
    settings = SupervisorSettings.from_json(sys.argv[1])
    return Supervisor(settings).run()


if __name__ == "__main__":
    sys.exit(main())
