#!/usr/bin/env python3
"""Run `claude remote-control` in ~/repo as a systemd user service that starts with the desktop session.

  claude_rc.py install            write and enable ~/.config/systemd/user/claude-rc.service
  claude_rc.py run                the service's command: reattach after a planned restart, else start fresh
  claude_rc.py restart [--delay]  restart the service on the installed binary, reattaching its session
  claude_rc.py handover --pid N   stop a remote-control started by hand (PID N) and start the service in its place

The service runs in the user's login shell, so it sees the same PATH and tools as a terminal, and starts
after the graphical session so agents can open hidden windows on it. KillMode=process: stopping or
restarting it ends remote-control only, never the background agent sessions its daemon runs.
A planned restart (`restart`, `handover`, `agent_session.py update`) leaves a marker; the next `run`
then passes --continue so the conversation carries on. Restarts are delayed so the session that asks
for one can finish its reply first.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

UNIT = "claude-rc.service"
UNIT_FILE = Path.home() / ".config" / "systemd" / "user" / UNIT
WORKDIR = Path.home() / "repo"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "claude-rc"
CONTINUE_MARKER = STATE / "continue"
# claude remote-control --continue only finds a session recorded within about 4 hours.
CONTINUE_WINDOW_S = 3 * 3600
TOOL = Path(__file__).resolve()
HARNESS = TOOL.parent.parent


def refuse(message: str) -> None:
    sys.exit("claude_rc: " + message)


def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], check=check, capture_output=True, text=True)


def unit_text(shell: str) -> str:
    command = "exec uv run --frozen --project %s python %s run" % (HARNESS, TOOL)
    return "\n".join([
        "[Unit]",
        "Description=Claude Code Remote Control in %s" % WORKDIR,
        "After=graphical-session.target",
        "PartOf=graphical-session.target",
        "",
        "[Service]",
        "WorkingDirectory=%s" % WORKDIR,
        "ExecStart=%s -i -c '%s'" % (shell, command),
        "KillMode=process",
        "Restart=on-failure",
        "RestartSec=10",
        "",
        "[Install]",
        "WantedBy=graphical-session.target",
        "",
    ])


def install(_: argparse.Namespace) -> int:
    shell = os.environ.get("SHELL") or refuse("SHELL is not set")
    if shutil.which("claude") is None:
        refuse("claude is not on PATH")
    UNIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    UNIT_FILE.write_text(unit_text(shell))
    systemctl("daemon-reload")
    systemctl("enable", UNIT)
    print("installed and enabled %s (starts with the desktop session)" % UNIT_FILE)
    print("start it with: claude_rc.py handover --pid <pid of a hand-started remote-control>, "
          "or systemctl --user start %s" % UNIT)
    return 0


def run(_: argparse.Namespace) -> int:
    argv = ["claude", "remote-control"]
    if CONTINUE_MARKER.exists():
        fresh = time.time() - CONTINUE_MARKER.stat().st_mtime < CONTINUE_WINDOW_S
        CONTINUE_MARKER.unlink()
        if fresh:
            argv.append("--continue")
    os.chdir(WORKDIR)
    os.execvp(argv[0], argv)
    return 1


def mark_continue() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    CONTINUE_MARKER.touch()


def schedule(delay: int, *command: str) -> None:
    """A transient timer runs outside the service, so it survives the restart it causes."""
    subprocess.run(["systemd-run", "--user", "--collect", "--on-active=%ds" % delay,
                    "--unit=claude-rc-restart-%d" % int(time.time()), *command],
                   check=True, capture_output=True, text=True)


def running_versions() -> set[str]:
    """Claude Code binaries (versions/<version>) running inside the active service."""
    shown = systemctl("show", "-p", "ActiveState", "-p", "ControlGroup", UNIT, check=False).stdout
    fields = dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)
    if fields.get("ActiveState") != "active" or not fields.get("ControlGroup"):
        return set()
    procs = Path("/sys/fs/cgroup") / fields["ControlGroup"].lstrip("/") / "cgroup.procs"
    found = set()
    for pid in procs.read_text().split():
        try:
            exe = Path(os.readlink("/proc/%s/exe" % pid))
        except OSError:
            continue
        if exe.parent.name == "versions":
            found.add(exe.name)
    return found


def restart_if_stale(version: str, delay: int) -> bool:
    """Schedules a restart when the service runs a binary other than `version`."""
    if not running_versions() - {version}:
        return False
    schedule_restart(delay)
    return True


def schedule_restart(delay: int) -> None:
    mark_continue()
    schedule(delay, "systemctl", "--user", "restart", UNIT)
    print("%s restarts in %d s and reattaches its session" % (UNIT, delay))


def restart(args: argparse.Namespace) -> int:
    if not UNIT_FILE.exists():
        refuse("%s is not installed; run claude_rc.py install" % UNIT)
    schedule_restart(args.delay)
    return 0


def handover(args: argparse.Namespace) -> int:
    if not UNIT_FILE.exists():
        refuse("%s is not installed; run claude_rc.py install" % UNIT)
    if args.wait:
        os.kill(args.pid, signal.SIGTERM)
        deadline = time.monotonic() + 60
        while Path("/proc/%d" % args.pid).exists():
            if time.monotonic() > deadline:
                refuse("remote-control %d did not exit within 60 s; the service was not started" % args.pid)
            time.sleep(0.5)
        systemctl("start", UNIT)
        return 0
    cmdline = Path("/proc/%d/cmdline" % args.pid).read_bytes().split(b"\0")
    if not any(part in (b"rc", b"remote-control") for part in cmdline):
        refuse("PID %d is not a claude remote-control" % args.pid)
    mark_continue()
    schedule(args.delay, "uv", "run", "--frozen", "--project", str(HARNESS), "python", str(TOOL),
             "handover", "--pid", str(args.pid), "--wait")
    print("remote-control %d stops in %d s; %s then starts and reattaches its session" %
          (args.pid, args.delay, UNIT))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="write and enable the user service").set_defaults(run=install)
    commands.add_parser("run", help="the service's command").set_defaults(run=run)
    again = commands.add_parser("restart", help="restart the service on the installed binary")
    again.add_argument("--delay", type=int, default=60, help="seconds before the restart (default 60)")
    again.set_defaults(run=restart)
    move = commands.add_parser("handover", help="replace a hand-started remote-control with the service")
    move.add_argument("--pid", type=int, required=True, help="PID of the `claude rc` process")
    move.add_argument("--delay", type=int, default=60, help="seconds before the switch (default 60)")
    move.add_argument("--wait", action="store_true", help=argparse.SUPPRESS)
    move.set_defaults(run=handover)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
