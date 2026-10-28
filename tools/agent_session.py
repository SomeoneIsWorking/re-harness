#!/usr/bin/env python3
"""Start and list separate Claude Code sessions, one per project.

A session started here is a top-level background session (``claude --bg``),
not a subagent: it runs in the project's own directory, picks up that
project's CLAUDE.md/AGENTS.md and memory, and the user can attach to it,
read its logs, or stop it like any session they started themselves.

  agent_session.py start <repo> --name <name> --prompt-file <file>
  agent_session.py start <repo> --name <name> --prompt "<text>"
  agent_session.py list

``start`` refuses when the directory is not yet trusted (the user accepts the
trust prompt once by running ``claude`` there) or a live session already has the
name or the directory,
runs ``claude --bg`` with the repo as its working directory (no ``cd`` in a
shell), then confirms through ``claude agents --json`` that the new session
is up in that directory. It prints the id and the commands to follow it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def sessions() -> list[dict]:
    reply = subprocess.run(["claude", "agents", "--json"], check=True,
                           capture_output=True, text=True)
    return json.loads(reply.stdout or "[]")


def trusted(repo: Path) -> bool:
    """Claude Code records an accepted trust prompt per directory."""
    config = Path.home() / ".claude.json"
    projects = json.loads(config.read_text()).get("projects", {})
    return bool(projects.get(str(repo), {}).get("hasTrustDialogAccepted"))


def refuse(message: str) -> None:
    print("agent_session: " + message, file=sys.stderr)
    sys.exit(2)


def start(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        refuse("%s is not a directory" % repo)
    if not trusted(repo):
        refuse("%s is not a trusted workspace, and claude --bg will not start "
               "there. The user accepts that once, in a terminal: run `claude` "
               "in %s, accept the trust prompt, exit, then start again. An "
               "agent never records trust itself." % (repo, repo))
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


def list_sessions(_: argparse.Namespace) -> int:
    live = sessions()
    for session in live:
        print("%-8s %-16s %-8s %s" % (session.get("id"), session.get("name"),
                                      session.get("state"), session.get("cwd")))
    print("%d session(s)" % len(live))
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
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
