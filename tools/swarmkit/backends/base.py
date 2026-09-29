"""The contract every worker backend implements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol


class Backend(Protocol):
    """Builds the argv that runs one non-interactive worker turn in the current directory.

    The runner owns the working directory, deadline, process group, and log; a
    backend only knows its CLI. A worker signals failure through a nonzero exit.
    """

    name: str

    def command(self, prompt: str, files: Sequence[str], model: str) -> list[str]: ...

    def environment(self, read_only: Sequence[Path]) -> Mapping[str, str]:
        """Extra environment confining the worker: ``read_only`` readable, nothing else outside."""
        ...
