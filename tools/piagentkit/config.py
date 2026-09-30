"""The one reader of the environment for piagent.

Every other module receives these values explicitly, so a test can point an
agent at a private state directory without touching the process environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STATE_DIR_VARIABLE = "PIAGENT_DIR"
DEFAULT_MODEL = "opencode/space-bunny-free"
DEFAULT_PI_BINARY = "pi"
FIRST_PROMPT_TIMEOUT_SECONDS = 60.0
# How long a control client waits for pi's matching response. Generous against a
# busy model server, short enough that a wedged agent reports instead of hanging.
RPC_TIMEOUT_SECONDS = 30.0
TERMINATE_GRACE_SECONDS = 5.0
POLL_SECONDS = 0.1


@dataclass(frozen=True)
class PiAgentConfig:
    """Where agents live and what binary runs them."""

    state_dir: Path
    state_dir_source: str
    pi_binary: str = DEFAULT_PI_BINARY
    model: str | None = DEFAULT_MODEL


def default_state_dir() -> Path:
    """``$PIAGENT_DIR``, else ``~/repo/scratch/piagent``."""
    configured = os.environ.get(STATE_DIR_VARIABLE)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "repo" / "scratch" / "piagent"


def build_config(
    state_dir: Path | None = None,
    pi_binary: str | None = None,
    model: str | None = None,
) -> PiAgentConfig:
    """The one place the environment becomes a typed config; flags win."""
    if state_dir is not None:
        resolved, source = state_dir.expanduser(), "--state-dir"
    else:
        resolved, source = default_state_dir(), f"${STATE_DIR_VARIABLE} or the default"
    return PiAgentConfig(
        state_dir=resolved,
        state_dir_source=source,
        pi_binary=pi_binary or DEFAULT_PI_BINARY,
        model=model or DEFAULT_MODEL,
    )
