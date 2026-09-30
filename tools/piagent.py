#!/usr/bin/env python3
"""Drive one long-running pi agent by name, without holding the conversation.

``start`` spawns a detached supervisor that owns ``pi --mode rpc``; every later
command talks to that supervisor over a UNIX socket, so an agent can be steered,
questioned, and stopped long after the command that launched it. The event
stream is kept verbatim under ``<state-dir>/<name>/``; nothing is ever committed.

    piagent.py start NAME --cwd DIR [--message TEXT | --brief FILE] [--model M]
    piagent.py send NAME TEXT [--follow-up]
    piagent.py status NAME
    piagent.py tail NAME [-n N] [--follow]
    piagent.py wait NAME [--timeout S]
    piagent.py abort NAME
    piagent.py stop NAME
    piagent.py list

See skills/global/piagent/SKILL.md for when to use this instead of swarm.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from piagentkit import control, views
from piagentkit.config import build_config
from piagentkit.control import IDLE, Refused
from piagentkit.paths import NameRefused

DEFAULT_TAIL_EVENTS = 40
DEFAULT_WAIT_SECONDS = 900.0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = build_config(
        getattr(args, "state_dir", None),
        getattr(args, "pi_binary", None),
        getattr(args, "model", None),
    )
    try:
        return args.handler(args, config)
    except (Refused, NameRefused) as error:
        print(f"piagent: refused: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # The same three options before or after the subcommand. SUPPRESS keeps an
    # unused subcommand option from overwriting a value given at the top level.
    common.add_argument("--state-dir", type=Path, default=argparse.SUPPRESS,
                        help="agent state root (default: $PIAGENT_DIR)")
    common.add_argument("--pi-binary", default=argparse.SUPPRESS,
                        help="pi executable to run (default: pi)")
    common.add_argument("--model", default=argparse.SUPPRESS,
                        help="model pattern passed to pi (default: opencode/space-bunny-free)")
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0], parents=[common])
    commands = top.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", parents=[common],
                                help="launch a detached agent and send its first prompt")
    start.add_argument("name")
    start.add_argument("--cwd", type=Path, required=True, help="working directory for the agent")
    start.add_argument("--brief", type=Path, help="file whose contents are the first prompt")
    start.add_argument("--message", help="first prompt text; with neither, the agent starts idle")
    start.add_argument("--thinking", dest="thinking_level", help="thinking level for pi")
    start.add_argument("--session-dir", type=Path, help="pi session directory")
    start.set_defaults(handler=command_start)

    send = commands.add_parser("send", parents=[common],
                                help="prompt, steer, or follow up on a running agent")
    send.add_argument("name")
    send.add_argument("text")
    send.add_argument("--follow-up", action="store_true", help="queue until the agent finishes")
    send.set_defaults(handler=command_send)

    status = commands.add_parser("status", parents=[common],
                                 help="one compact block about one agent")
    status.add_argument("name")
    status.set_defaults(handler=command_status)

    tail = commands.add_parser("tail", parents=[common],
                               help="human-readable transcript of recent events")
    tail.add_argument("name")
    tail.add_argument("-n", "--events", type=positive, default=DEFAULT_TAIL_EVENTS)
    tail.add_argument("--follow", action="store_true", help="stream until the agent settles")
    tail.set_defaults(handler=command_tail)

    wait = commands.add_parser("wait", parents=[common],
                               help="block until the agent settles")
    wait.add_argument("name")
    wait.add_argument("--timeout", type=float, default=DEFAULT_WAIT_SECONDS)
    wait.set_defaults(handler=command_wait)

    abort = commands.add_parser("abort", parents=[common],
                                help="stop the current run; the agent stays alive")
    abort.add_argument("name")
    abort.set_defaults(handler=command_abort)

    stop = commands.add_parser("stop", parents=[common],
                               help="end the agent and its supervisor by pid")
    stop.add_argument("name")
    stop.set_defaults(handler=command_stop)

    listing = commands.add_parser("list", parents=[common],
                                  help="every agent in the state directory")
    listing.set_defaults(handler=command_list)
    return top


def positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def command_start(args: argparse.Namespace, config) -> int:
    outcome = control.start(
        control.StartSettings(
            config=config,
            name=args.name,
            cwd=args.cwd,
            brief=args.brief,
            message=args.message,
            thinking_level=args.thinking_level,
            session_dir=args.session_dir,
        )
    )
    print(f"piagent: started {outcome.name} (supervisor pid {outcome.supervisor_pid}, pi pid {outcome.pi_pid})")
    print(f"piagent: state {outcome.state_dir}")
    if outcome.disposition == IDLE:
        print(f"piagent: no first prompt; send one with `piagent.py send {outcome.name} <text>`")
    else:
        print(f"piagent: first prompt {outcome.disposition}; watch with `piagent.py tail {outcome.name} --follow`")
    return 0


def command_send(args: argparse.Namespace, config) -> int:
    target = control.agent(config, args.name)
    disposition = target.send(args.text, follow_up=args.follow_up)
    print(f"piagent: {target.name} <- {disposition}")
    return 0


def command_status(args: argparse.Namespace, config) -> int:
    for line in control.agent(config, args.name).status_lines():
        print(line)
    return 0


def command_tail(args: argparse.Namespace, config) -> int:
    target = control.agent(config, args.name)
    target.require_meta()
    if args.follow:
        for line in target.follow():
            print(line, flush=True)
        return 0
    for line in target.tail_lines(args.events):
        print(line)
    return 0


def command_wait(args: argparse.Namespace, config) -> int:
    target = control.agent(config, args.name)
    target.require_meta()
    code, text = target.wait(args.timeout)
    if text:
        print(text)
    reason = {control.SETTLED: "settled", control.DEAD: "agent is dead", control.TIMED_OUT: "timed out"}[code]
    print(f"piagent: {target.name} {reason}", file=sys.stderr)
    return code


def command_abort(args: argparse.Namespace, config) -> int:
    target = control.agent(config, args.name)
    print(f"piagent: {target.abort()}")
    return 0


def command_stop(args: argparse.Namespace, config) -> int:
    result = control.agent(config, args.name).stop()
    gone = result["supervisor_gone"] and result["pi_gone"]
    print(
        f"piagent: {'aborted' if result['aborted'] else 'not aborted'}, "
        f"supervisor {'gone' if result['supervisor_gone'] else 'STILL ALIVE'}, "
        f"pi {'gone' if result['pi_gone'] else 'STILL ALIVE'}"
    )
    print(f"piagent: logs kept in {result['directory']}")
    return 0 if gone else 1


def command_list(args: argparse.Namespace, config) -> int:
    rows = control.list_agents(config)
    print(views.list_header())
    for row in rows:
        print(row.render())
    print(f"piagent: {len(rows)} agent(s) in {config.state_dir} (from {config.state_dir_source})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
