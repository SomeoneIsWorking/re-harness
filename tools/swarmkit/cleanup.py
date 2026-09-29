"""Remove one run's worktrees through git, touching only registered paths inside that run."""

from __future__ import annotations

import json
from pathlib import Path

from .console import emit
from .jobs import JOB_ID
from .results import RUN_FILE
from .runner import TREE_DIR
from .worktree import SWARM_SCRATCH, git, registered_worktrees, repo_root


class CleanupRefused(RuntimeError):
    """The target is not a swarm run directory; nothing was removed."""


def remove_worktrees(run_dir: Path) -> int:
    run_dir = run_dir.resolve()
    if not (run_dir / RUN_FILE).is_file():
        raise CleanupRefused(f"{run_dir} has no {RUN_FILE}")
    root = repo_root(run_dir.parent)
    if run_dir.parent != root / SWARM_SCRATCH:
        raise CleanupRefused(f"{run_dir} is not directly under {root / SWARM_SCRATCH}")
    ids = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))["jobs"]
    registered = registered_worktrees(root)
    removed = 0
    for job_id in ids:
        if not JOB_ID.match(job_id):
            raise CleanupRefused(f"{RUN_FILE} lists unsafe job id {job_id!r}")
        tree = run_dir / job_id / TREE_DIR
        if tree.resolve() not in registered:
            continue
        git(root, "worktree", "remove", "--force", str(tree))
        removed += 1
    emit(
        f"swarm gc: scanned {len(ids)} job(s), removed {removed} worktree(s) in {run_dir}"
    )
    return removed
