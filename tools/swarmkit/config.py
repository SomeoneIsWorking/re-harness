"""The one reader of the environment for the swarm runner.

Every other swarm module receives these values explicitly, so a test can build a
config pointing at a private lock directory without touching the process
environment.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "opencode/space-bunny-free"
DEFAULT_WORKERS = 8
LOCK_DIR_VARIABLE = "SWARM_LOCK_DIR"


def default_lock_dir() -> Path:
    """``$SWARM_LOCK_DIR``, else ``~/repo/scratch/locks`` (the portfolio's shared lock root)."""
    configured = os.environ.get(LOCK_DIR_VARIABLE)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "repo" / "scratch" / "locks"
