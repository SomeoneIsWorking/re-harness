"""``opencode run`` worker.

``--standalone`` runs a private model server as a child of the worker instead of
routing through the user's background ``opencode serve --service``. Only then
does killing the worker's process group on timeout actually stop the session;
through the shared service a timed-out session would keep editing the worktree.
"""

from __future__ import annotations

from collections.abc import Sequence


class OpencodeBackend:
    name = "opencode"

    def command(self, prompt: str, files: Sequence[str], model: str) -> list[str]:
        argv = ["opencode", "run", "--standalone", "-m", model, "--format", "json"]
        for attached in files:
            argv += ["-f", attached]
        return argv + ["--", prompt]
