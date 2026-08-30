"""Git-history preconditions for project information evidence."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable


GitRunner = Callable[..., tuple[int, str]]


def shallow_repositories(repos: Iterable[str], root: str, git: GitRunner) -> list[str]:
    """Return indexed repositories whose visible history is incomplete.

    Symbol staleness is measured with ``git log -L``. At a shallow boundary Git attributes every
    surviving line to the boundary commit, which can manufacture both a new symbol change and a
    false verification result. There is no honest degraded mode: callers must refuse until the
    history the instrument is defined over has been fetched.
    """
    shallow = []
    for repo in repos:
        rc, out = git(repo, "rev-parse", "--is-shallow-repository")
        if rc == 0 and out.strip() == "true":
            shallow.append(os.path.relpath(repo, root))
    return shallow
