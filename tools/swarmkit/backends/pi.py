"""``pi -p`` worker; pi reaches Space Bunny as ``opencode/space-bunny-free``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .base import PROMPT_ATTACHED


class PiBackend:
    name = "pi"

    def command(self, task_file: Path, files: Sequence[str], model: str) -> list[str]:
        argv = ["pi", "-p", "--no-session", "--model", model, "--"]
        attached = [f"@{path}" for path in [str(task_file), *files]]
        return argv + attached + [PROMPT_ATTACHED]

    def environment(self, read_only: Sequence[Path]) -> Mapping[str, str]:
        # pi has no path permissions to configure: it can already read ``read_only``.
        return {}
