"""``pi -p`` worker; pi reaches Space Bunny as ``opencode/space-bunny-free``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .base import PROMPT_ATTACHED

# A worker needs the model, its tools and the repo's context files, nothing the
# operator's interactive pi loads: user extensions (PiNest's remote-control host,
# auto-update) cost ~380 MB per process (550 MB vs 166 MB measured), so eight
# workers spent 3 GB on UI nobody sees.
PI_WORKER_FLAGS = ("--no-extensions", "--no-prompt-templates", "--no-themes")


class PiBackend:
    name = "pi"

    def command(self, task_file: Path, files: Sequence[str], model: str) -> list[str]:
        argv = ["pi", "-p", "--no-session", *PI_WORKER_FLAGS, "--model", model, "--"]
        attached = [f"@{path}" for path in [str(task_file), *files]]
        return argv + attached + [PROMPT_ATTACHED]

    def environment(self, read_only: Sequence[Path]) -> Mapping[str, str]:
        # pi has no path permissions to configure: it can already read ``read_only``.
        return {}
