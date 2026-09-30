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
# The kinds a unit is registered as, for the guard's and the watchdog's reports.
UNIT_KINDS = ("build", "run", "swarm")
# Below PRESSURE_PAUSE_MIB the guard pauses the newest running unit; above
# PRESSURE_RESUME_MIB the paused ones are resumed. The gap is the hysteresis that
# stops a host hovering at the threshold from pausing and resuming forever. The
# guard must act before Claude Code's own low-memory reaper, which on 2026-09-30
# killed two swarm launchers outright at about 1 GiB available, in the same
# seconds that the guard, then pausing at 1024 MiB, paused its first two units.
PRESSURE_PAUSE_MIB = 2048
PRESSURE_RESUME_MIB = 3584
# Below PRESSURE_CRITICAL_MIB the guard pauses every poll regardless of settling,
# keeping clear of Claude Code's reaper near 1 GiB. PRESSURE_SETTLE_SECONDS is the
# wait after a pause or resume before the next one, so each can take effect.
PRESSURE_CRITICAL_MIB = 1400
PRESSURE_SETTLE_SECONDS = 5.0
LOCK_DIR_VARIABLE = "SWARM_LOCK_DIR"


def default_lock_dir() -> Path:
    """``$SWARM_LOCK_DIR``, else ``~/repo/scratch/locks`` (the portfolio's shared lock root)."""
    configured = os.environ.get(LOCK_DIR_VARIABLE)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "repo" / "scratch" / "locks"


def guard_heartbeat(lock_dir: Path) -> Path:
    """The file the pressure guard touches every poll; its age tells whether it runs."""
    return lock_dir / "guard" / "heartbeat"
