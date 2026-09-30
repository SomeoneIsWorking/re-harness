"""One agent's on-disk layout: ``<state-dir>/<name>/``.

Every file name is a property of this module so the supervisor, the CLI, and the
tests agree on where a run's log, metadata, and control socket live.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
EVENTS = "events.jsonl"
STDERR_LOG = "stderr.log"
SUPERVISOR_LOG = "supervisor.log"
META = "meta.json"
CONTROL_SOCKET = "ctl.sock"
FIRST_PROMPT = "first_prompt.json"
CONTROL_SOCKET_MODE = 0o600


class NameRefused(ValueError):
    """The requested agent name cannot be a directory under the state dir."""


@dataclass(frozen=True)
class AgentPaths:
    """Every path owned by one named agent."""

    root: Path
    name: str

    def __post_init__(self) -> None:
        if not NAME.fullmatch(self.name):
            raise NameRefused(
                f"agent name {self.name!r} must match {NAME.pattern}: letters, "
                "digits, dot, dash, underscore"
            )
        if self.name in (".", ".."):
            raise NameRefused(f"agent name {self.name!r} is not a usable directory name")

    @property
    def directory(self) -> Path:
        return self.root / self.name

    @property
    def events(self) -> Path:
        return self.directory / EVENTS

    @property
    def stderr(self) -> Path:
        return self.directory / STDERR_LOG

    @property
    def supervisor_log(self) -> Path:
        return self.directory / SUPERVISOR_LOG

    @property
    def meta(self) -> Path:
        return self.directory / META

    @property
    def socket(self) -> Path:
        return self.directory / CONTROL_SOCKET

    @property
    def first_prompt(self) -> Path:
        return self.directory / FIRST_PROMPT

    def ensure(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)


def known_agents(root: Path) -> list[AgentPaths]:
    """Every agent directory under ``root``, name-sorted."""
    if not root.is_dir():
        return []
    found: list[AgentPaths] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and NAME.fullmatch(entry.name) and (entry / META).is_file():
            found.append(AgentPaths(root, entry.name))
    return found
