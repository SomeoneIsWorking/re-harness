#!/usr/bin/env python3
"""Start and list separate Claude Code sessions, one per project.

A session started here is a top-level background session (``claude --bg``),
not a subagent: it runs in the project's own directory, picks up that
project's CLAUDE.md/AGENTS.md and memory, and the user can attach to it,
read its logs, or stop it like any session they started themselves.

  agent_session.py start <repo> --name <name> --prompt-file <file>
  agent_session.py start <repo> --name <name> --prompt "<text>"
  agent_session.py list
  agent_session.py update

``start`` accepts Claude Code's trust prompt for a directory under ~/repo (the
user's own repos), refuses an untrusted one elsewhere or when a live session
already has the name or the directory,
runs ``claude --bg`` with the repo as its working directory (no ``cd`` in a
shell), then confirms through ``claude agents --json`` that the new session
is up in that directory. It prints the id and the commands to follow it.

``update`` runs ``claude update``, then ``claude respawn <id>`` for each
background session that runs an older binary and is not working (a working
session's background jobs would be killed). It ends by listing each session's
running version; run it again for a session left behind once it is idle.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sessions() -> list[dict]:
    reply = subprocess.run(["claude", "agents", "--json"], check=True,
                           capture_output=True, text=True)
    return json.loads(reply.stdout or "[]")


CONFIG = Path.home() / ".claude.json"
# The user's own repos; the tool accepts the trust prompt only under here.
OWN_REPOS = Path.home() / "repo"


def trusted(repo: Path) -> bool:
    """Claude Code records an accepted trust prompt per directory."""
    projects = json.loads(CONFIG.read_text()).get("projects", {})
    return bool(projects.get(str(repo), {}).get("hasTrustDialogAccepted"))


def trust(repo: Path) -> None:
    """Record the trust prompt as accepted for `repo`, as the dialog would.
    Written to a sibling file and renamed, so a reader never sees half a file."""
    config = json.loads(CONFIG.read_text())
    entry = config.setdefault("projects", {}).setdefault(str(repo), {})
    entry["hasTrustDialogAccepted"] = True
    staged = CONFIG.with_name(CONFIG.name + ".agent_session")
    staged.write_text(json.dumps(config, indent=2))
    staged.replace(CONFIG)
    print("trusted %s (the user's own repos accept the prompt through this "
          "tool)" % repo)


def refuse(message: str) -> None:
    print("agent_session: " + message, file=sys.stderr)
    sys.exit(2)


def start(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        refuse("%s is not a directory" % repo)
    if not trusted(repo):
        if not repo.is_relative_to(OWN_REPOS):
            refuse("%s is not a trusted workspace and is outside %s; the user "
                   "accepts it once by running `claude` there" % (repo,
                                                                OWN_REPOS))
        trust(repo)
    if args.prompt_file:
        prompt = Path(args.prompt_file).expanduser().read_text()
    else:
        prompt = args.prompt or ""
    if not prompt.strip():
        refuse("the prompt is empty")
    for live in sessions():
        if live.get("name") == args.name:
            refuse("a session named %r is already running (id %s, %s)" %
                   (args.name, live.get("id"), live.get("cwd")))
        if live.get("cwd") == str(repo) and not args.allow_shared_dir:
            refuse("session %r (id %s) already runs in %s; pass "
                   "--allow-shared-dir to start a second one there" %
                   (live.get("name"), live.get("id"), repo))
    argv = ["claude", "--bg", "--name", args.name]
    if args.model:
        argv += ["--model", args.model]
    if args.effort:
        argv += ["--effort", args.effort]
    argv.append(prompt)
    launched = subprocess.run(argv, cwd=repo, capture_output=True, text=True)
    output = launched.stdout + launched.stderr
    if launched.returncode != 0:
        refuse("claude --bg failed (%d): %s" % (launched.returncode,
                                                output.strip()))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for live in sessions():
            if live.get("name") == args.name:
                if live.get("cwd") != str(repo):
                    refuse("session %s started in %s, not %s" %
                           (live.get("id"), live.get("cwd"), repo))
                print("started %r: id %s in %s (%s)" %
                      (args.name, live.get("id"), repo, live.get("state")))
                print("  follow: claude logs %s | attach: claude attach %s | "
                      "stop: claude stop %s" % ((live.get("id"),) * 3))
                return 0
        time.sleep(1)
    match = re.search(r"\b[0-9a-f]{8}\b", output)
    refuse("claude --bg returned but no session named %r appeared in "
           "`claude agents --json` within 30 s (it printed: %s)" %
           (args.name, match.group(0) if match else output.strip()))
    return 2


def running_version(pid: int | None) -> str:
    """Claude Code runs from versions/<version>; a session's binary names it."""
    if pid is None:
        return "stopped"
    try:
        return Path(os.readlink("/proc/%d/exe" % pid)).name
    except OSError:
        return "stopped"


def installed_version() -> str:
    claude = shutil.which("claude")
    if claude is None:
        refuse("claude is not on PATH")
    return Path(claude).resolve().name


def list_sessions(_: argparse.Namespace) -> int:
    live = sessions()
    current = installed_version()
    for session in live:
        version = running_version(session.get("pid"))
        print("%-8s %-24s %-8s %-9s%s %s" % (
            session.get("id"), session.get("name"), session.get("state"),
            version, " " if version in (current, "stopped") else "*",
            session.get("cwd")))
    print("%d session(s); installed %s, * runs an older version" %
          (len(live), current))
    return 0


def update(args: argparse.Namespace) -> int:
    before = installed_version()
    subprocess.run(["claude", "update"], check=True)
    after = installed_version()
    print("claude %s -> %s" % (before, after) if after != before
          else "claude %s is the latest" % after)
    # respawn --all also restarts working sessions and kills their background jobs.
    failed = []
    for session in sessions():
        behind = running_version(session.get("pid")) not in (after, "stopped")
        working = session.get("state") == "working" or session.get("status") == "busy"
        if behind and working:
            print("left %s (%s) running: it is working" % (session.get("id"), session.get("name")))
        elif behind and session.get("id"):
            if subprocess.run(["claude", "respawn", session["id"]]).returncode != 0:
                failed.append(session["id"])
    list_sessions(args)
    if failed:
        print("could not respawn: %s" % " ".join(failed), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start", help="start a named session in a repo")
    begin.add_argument("repo")
    begin.add_argument("--name", required=True)
    prompt = begin.add_mutually_exclusive_group(required=True)
    prompt.add_argument("--prompt-file")
    prompt.add_argument("--prompt")
    begin.add_argument("--model")
    begin.add_argument("--effort")
    begin.add_argument("--allow-shared-dir", action="store_true")
    begin.set_defaults(run=start)
    show = commands.add_parser("list", help="list live sessions")
    show.set_defaults(run=list_sessions)
    upgrade = commands.add_parser(
        "update", help="update Claude Code and restart idle background sessions on it")
    upgrade.set_defaults(run=update)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
