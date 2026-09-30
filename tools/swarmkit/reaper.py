"""Run one command as the direct child of a wrapper, and leave nothing behind.

    command_argv(<command>, parent=<wrapper pid>)   # how a wrapper starts it

``PR_SET_PDEATHSIG`` reaches exactly the process it was set on. A wrapper whose
direct child is ``cmake`` therefore lost ``ninja``, ``cc1plus`` and everything
below them when it was killed: each orphan was reparented to init and kept
compiling against a gate the run had already given up on. This process is the
wrapper's direct child instead, and it is the owner of the whole subtree:

* it makes itself a child subreaper before starting the command, so a
  descendant whose own parent died is reparented to it rather than to init and
  cannot escape the wrapper's death;
* it arms ``PR_SET_PDEATHSIG`` (SIGTERM, catchable) on itself as its first act
  and refuses to start the command if the wrapper named on its command line is
  no longer its parent, so a wrapper killed before or after the arming takes it
  down either way. Arming itself, rather than through a ``preexec_fn`` hook,
  keeps the fork of a multithreaded wrapper (the swarm runner) free of Python
  code between fork and exec;
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
# The directory that holds the ``swarmkit`` package. The bootstrap puts it on the
# reaper's own sys.path only, so the command inherits the caller's environment
# unchanged: a PYTHONPATH naming the harness tools could shadow a project's modules.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from swarmkit.reaper import main; sys.exit(main(sys.argv[1:]))"
)
LAUNCH_FAILURE_EXIT = 127
_LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
_LIBC.prctl.argtypes = [
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
_LIBC.prctl.restype = ctypes.c_int


def command_argv(argv: Sequence[str], parent: int) -> list[str]:
    """The wrapper's direct child: the reaper, owned by ``parent``, running ``argv``."""
    return [sys.executable, "-c", BOOTSTRAP, str(PACKAGE_ROOT), str(parent), "--", *argv]


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
    """``argv`` is ``<parent pid> -- <command> [args...]``, as ``command_argv`` builds it."""
    if len(argv) < 3 or argv[1] != "--" or not argv[0].isdigit():
        sys.exit("reaper: usage: <parent pid> -- <command> [args...]")
    parent, command = int(argv[0]), list(argv[2:])
    if _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        return PRCTL_FAILURE_EXIT
    # A wrapper that died before the prctl above sends no signal; its child is
    # already reparented, so it refuses to start the command at all.
    if os.getppid() != parent:
        return 1
    if _LIBC.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        reason = os.strerror(ctypes.get_errno())
        sys.exit(f"reaper: prctl(PR_SET_CHILD_SUBREAPER) failed: {reason}")
    # The one place a hook is unavoidable: nothing else can set
    # PR_SET_PDEATHSIG between the fork and the exec. It runs in the
    # single-threaded child and does nothing but prctl, getppid and _exit -- no
    # import, no allocation, no lock a killed thread could hold.
    try:
        child = subprocess.Popen(
            command,
            close_fds=True,
            preexec_fn=die_with_parent(os.getpid()),  # noqa: PLW1509
        )
    except OSError as error:
        print(f"reaper: could not launch {command[0]!r}: {error}", file=sys.stderr)
        return LAUNCH_FAILURE_EXIT
    previous = _forward_signals(child.pid)
    try:
        status = _wait_reaping_adopted(child)
    finally:
        _restore_signals(previous)
    reap_descendants(os.getpid())
    return exit_status(status)


def _wait_reaping_adopted(child: subprocess.Popen[bytes]) -> int:
    """Wait for ``child`` while reaping every orphan this subreaper adopts meanwhile.

    A subreaper that waits only for its own child leaves each adopted orphan a
    zombie until that child ends, and a zombie still answers ``kill(pid, 0)``,
    so it looked alive to every liveness check for as long as its worker ran.
    """
    while True:
        reaped, status = os.waitpid(-1, 0)
        if reaped == child.pid:
            child.returncode = os.waitstatus_to_exitcode(status)
            return child.returncode


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
