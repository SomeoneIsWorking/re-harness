"""``opencode run`` worker.

``opencode run`` serves the model in its own process, so killing the worker's process
group on timeout stops the session. Each job gets its own ``OPENCODE_DB``: parallel
workers sharing the default database fail with "database is locked".

A non-interactive run treats opencode's default ``ask`` for a path outside the worktree
as a rejection that aborts the whole session ("Step interrupted"), so a worker that
merely looked at the main checkout died with nothing to show. The permission config
passed in ``OPENCODE_CONFIG_CONTENT`` denies such paths instead, which the worker sees
as an ordinary tool error, and allows reading (not editing) the job's ``read_only``
directories. opencode applies the last matching rule, so the catch-all comes first.
The task file the runner wrote is one of those readable directories.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .base import PROMPT_ATTACHED


class OpencodeBackend:
    name = "opencode"

    def command(self, task_file: Path, files: Sequence[str], model: str) -> list[str]:
        argv = ["opencode", "run", "-m", model, "--format", "json"]
        for attached in [str(task_file), *files]:
            argv += ["-f", attached]
        return argv + ["--", PROMPT_ATTACHED]

    def environment(
        self, read_only: Sequence[Path], state_dir: Path
    ) -> Mapping[str, str]:
        outside = {"*": "deny"} | {f"{path}/**": "allow" for path in read_only}
        edit = {"*": "allow"} | {f"{path}/**": "deny" for path in read_only}
        permission = {"external_directory": outside, "edit": edit}
        return {
            "OPENCODE_CONFIG_CONTENT": json.dumps({"permission": permission}),
            "OPENCODE_DB": str(state_dir / "opencode.db"),
        }
