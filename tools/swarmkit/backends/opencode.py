"""``opencode run`` worker.

``--standalone`` runs a private model server as a child of the worker instead of
routing through the user's background ``opencode serve --service``. Only then
does killing the worker's process group on timeout actually stop the session;
through the shared service a timed-out session would keep editing the worktree.

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
        argv = ["opencode", "run", "--standalone", "-m", model, "--format", "json"]
        for attached in [str(task_file), *files]:
            argv += ["-f", attached]
        return argv + ["--", PROMPT_ATTACHED]

    def environment(self, read_only: Sequence[Path]) -> Mapping[str, str]:
        outside = {"*": "deny"} | {f"{path}/**": "allow" for path in read_only}
        edit = {"*": "allow"} | {f"{path}/**": "deny" for path in read_only}
        permission = {"external_directory": outside, "edit": edit}
        return {"OPENCODE_CONFIG_CONTENT": json.dumps({"permission": permission})}
