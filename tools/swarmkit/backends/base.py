"""The contract every worker backend implements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

# The task is attached, never inlined: Linux caps one argv string at 128 KiB
# (MAX_ARG_STRLEN), and a job's prompt plus gate feedback can exceed that, which
# failed the execve outright. This short message is all the argv carries.
PROMPT_ATTACHED = (
    "Your complete task is the attached task file. Read it, then do what it says."
)


class Backend(Protocol):
    """Builds the argv that runs one non-interactive worker turn in the current directory.

    The runner owns the working directory, the task file, the deadline, the process
    group, and the log; a backend only knows its CLI. A worker signals failure
    through a nonzero exit.
    """

    name: str

    def command(
        self, task_file: Path, files: Sequence[str], model: str
    ) -> list[str]: ...

    def environment(self, read_only: Sequence[Path]) -> Mapping[str, str]:
        """Extra environment confining the worker: ``read_only`` readable, nothing else outside."""
        ...
