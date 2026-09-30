"""``meta.json``: what the supervisor records about its agent.

Written by the supervisor as the run develops and read by every CLI command, so
it is the single answer to "which processes own this agent, and how did it end".
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUNNING = "running"
DEAD = "dead"


@dataclass
class AgentMeta:
    """The supervisor's own record of one agent."""

    name: str
    cwd: str
    model: str | None
    started_at: float
    supervisor_pid: int
    pi_pid: int | None = None
    pi_binary: str = "pi"
    thinking_level: str | None = None
    session_dir: str | None = None
    state: str = RUNNING
    exit_code: int | None = None
    error: str | None = None
    argv: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        """Replace ``meta.json`` atomically; a reader never sees a partial file."""
        temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def mark_dead(self, exit_code: int | None, error: str | None = None) -> None:
        self.state = DEAD
        self.exit_code = exit_code
        if error:
            self.error = error

    @property
    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started_at)


def read(path: Path) -> AgentMeta | None:
    """Load a meta file, or None when it is absent, unreadable, or malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    known = {field_name for field_name in AgentMeta.__dataclass_fields__}
    try:
        return AgentMeta(**{key: value for key, value in data.items() if key in known})
    except TypeError:
        return None
