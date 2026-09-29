"""The one reader of the environment for the swarm runner.

Every other swarm module receives these values explicitly, so a test can build a
config pointing at a private lock directory without touching the process
environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "opencode/space-bunny-free"
DEFAULT_SLOTS = 24
DEFAULT_WORKERS = 8
DEFAULT_MEMORY_FLOOR_MIB = 3072
LOCK_DIR_VARIABLE = "SWARM_LOCK_DIR"


@dataclass(frozen=True)
class SwarmConfig:
    """Machine-wide coordination paths and limits shared by every swarm invocation."""

    lock_dir: Path
    slots: int = DEFAULT_SLOTS
    memory_floor_mib: int = DEFAULT_MEMORY_FLOOR_MIB

    @property
    def slot_dir(self) -> Path:
        return self.lock_dir / "swarm-slots"

    @property
    def heavy_lock(self) -> Path:
        return self.lock_dir / "heavy.lock"


def default_lock_dir() -> Path:
    """``$SWARM_LOCK_DIR``, else ``~/repo/scratch/locks`` (the portfolio's shared lock root)."""
    configured = os.environ.get(LOCK_DIR_VARIABLE)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "repo" / "scratch" / "locks"
