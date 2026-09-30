"""Run one command as the direct child of a wrapper, and leave nothing behind.

    python3 -m swarmkit.reaper -- <command> [args...]

``PR_SET_PDEATHSIG`` reaches exactly the process it was set on. A wrapper whose
direct child is ``cmake`` therefore lost ``ninja``, ``cc1plus`` and everything
below them when it was killed: each orphan was reparented to init and kept
compiling against a gate the run had already given up on. This process is the
wrapper's direct child instead, and it is the owner of the whole subtree:

* it makes itself a child subreaper before starting the command, so a
  descendant whose own parent died is reparented to it rather than to init and
  cannot escape the wrapper's death;
* it carries the wrapper's ``PR_SET_PDEATHSIG`` (SIGTERM, catchable, unlike the
  SIGKILL a bare child used to get) and refuses to start the command if the
  wrapper died between the fork and the prctl;
* it runs the command in the caller's own process group, exactly where the
  command used to be, so a group kill aimed at the caller still reaches it.

When the command ends -- and on SIGINT/SIGTERM/SIGHUP, which it forwards to the
command first -- every remaining descendant is found through the parent graph
(``/proc`` ppid, so a descendant that started a session of its own is still
found), given SIGTERM, given a named grace, and then SIGKILLed. The exit status
is the command's.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType

from .procs import descendants, process_running

FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
PR_SET_PDEATHSIG = 1
PR_SET_CHILD_SUBREAPER = 36
# 126 is the shell's "cannot execute", here "cannot arm the subtree contract":
# running a command whose descendants could outlive the wrapper is exactly the
# failure this process exists to prevent, so it refuses rather than runs one.
PRCTL_FAILURE_EXIT = 126
# Long enough for a compiler or a test runner to finish what it is doing and
# exit on its own, short enough that a killed wrapper's gate is not still
# holding memory and CPU when the next run starts.
TERM_GRACE_SECONDS = 5.0
POLL_SECONDS = 0.05
# The directory that holds the ``swarmkit`` package, so the wrapper's child can
# run this module with ``-m`` no matter what the wrapper's own sys.path was.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
_LIBC.prctl.argtypes = [
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
_LIBC.prctl.restype = ctypes.c_int


def command_argv(argv: Sequence[str]) -> list[str]:
    """The wrapper's direct child: this module, running ``argv``."""
    return [sys.executable, "-m", __name__, "--", *argv]


def command_environment() -> dict[str, str]:
    """The child's environment, with this package importable by ``-m``."""
    return dict(os.environ, **command_environment_overrides())


def command_environment_overrides() -> dict[str, str]:
    """The variables ``command_argv`` needs on top of the caller's environment."""
    root = str(PACKAGE_ROOT)
    inherited = os.environ.get("PYTHONPATH")
    return {"PYTHONPATH": f"{root}{os.pathsep}{inherited}" if inherited else root}


def die_with_parent(parent: int, signum: int = signal.SIGTERM) -> Callable[[], None]:
    """Build a child's ``preexec_fn``: take ``signum`` with the wrapper, if it lives."""

    def arm() -> None:
        if _LIBC.prctl(PR_SET_PDEATHSIG, signum, 0, 0, 0) != 0:
            os._exit(PRCTL_FAILURE_EXIT)
        # The wrapper can die between the fork and the prctl above, and the signal
        # that would have told this child is not delivered to one already
        # reparented. It refuses to start the command instead of becoming an
        # orphan of it.
        if os.getppid() != parent:
            os._exit(1)

    return arm


def reap_descendants(pid: int, grace: float = TERM_GRACE_SECONDS) -> None:
    """Take down every remaining descendant: SIGTERM, grace, then SIGKILL."""
    _signal_tree(pid, signal.SIGTERM)
    if _wait_gone(pid, grace):
        return
    _signal_tree(pid, signal.SIGKILL)
    _wait_gone(pid, grace)


def exit_status(status: int) -> int:
    """A command's wait status as a shell reports it: its own, or 128 + its signal."""
    return 128 - status if status < 0 else status


def main(argv: Sequence[str]) -> int:
    command = list(argv[1:] if argv[:1] == ["--"] else argv)
    if not command:
        sys.exit("reaper: no command given (use: -m swarmkit.reaper -- <command> ...)")
    if _LIBC.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        reason = os.strerror(ctypes.get_errno())
        sys.exit(f"reaper: prctl(PR_SET_CHILD_SUBREAPER) failed: {reason}")
    # The one place a hook is unavoidable: nothing else can set
    # PR_SET_PDEATHSIG between the fork and the exec. It runs in the
    # single-threaded child and does nothing but prctl, getppid and _exit -- no
    # import, no allocation, no lock a killed thread could hold.
    child = subprocess.Popen(
        command,
        close_fds=True,
        preexec_fn=die_with_parent(os.getpid()),  # noqa: PLW1509
    )
    previous = _forward_signals(child.pid)
    try:
        status = child.wait()
    finally:
        _restore_signals(previous)
    reap_descendants(os.getpid())
    return exit_status(status)


def _signal_tree(pid: int, signum: int) -> None:
    for child in _live(pid):
        try:
            os.kill(child, signum)
        except ProcessLookupError:
            pass


def _wait_gone(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        _collect_orphans()
        if not _live(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def _live(pid: int) -> list[int]:
    """Descendants of ``pid`` that are still running; an adopted zombie is already done."""
    return [child for child in descendants(pid) if process_running(child)]


def _collect_orphans() -> None:
    """Reap the descendants this process adopted, so they leave ``/proc`` at once."""
    while True:
        try:
            reaped, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if reaped == 0:
            return


def _forward_signals(pid: int) -> dict[int, object]:
    def forward(signum: int, _frame: FrameType | None) -> None:
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    return {signum: signal.signal(signum, forward) for signum in FORWARDED_SIGNALS}


def _restore_signals(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)  # type: ignore[arg-type]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
