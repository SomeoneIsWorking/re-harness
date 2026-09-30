"""Detached git worktrees that isolate each worker from the main tree."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

SWARM_SCRATCH = Path("scratch") / "swarm"
BASE_FILE = "base"


class WorktreeError(RuntimeError):
    """A git operation the swarm depends on failed; the message carries git's output."""


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} in {repo}: {done.stderr.strip()}")
    return done.stdout


def repo_root(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--show-toplevel").strip()).resolve()


def run_directory(repo: Path, run_name: str) -> Path:
    """``<repo>/scratch/swarm/<run>``, refused unless git ignores it."""
    root = repo_root(repo)
    relative = SWARM_SCRATCH / run_name
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", str(relative)],
        capture_output=True,
        check=False,
    )
    if ignored.returncode != 0:
        raise WorktreeError(
            f"{root}: {relative} is not gitignored; add scratch/ to .gitignore"
        )
    return root / relative


def registered_worktrees(repo: Path) -> set[Path]:
    listing = git(repo, "worktree", "list", "--porcelain")
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in listing.splitlines()
        if line.startswith("worktree ")
    }


@dataclass(frozen=True)
class Worktree:
    repo: Path
    path: Path
    base: str

    @classmethod
    def create(cls, repo: Path, path: Path) -> Worktree:
        """Check out the repo's current HEAD, detached, at ``path``."""
        base = git(repo, "rev-parse", "HEAD").strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "--detach", str(path), base)
        (path.parent / BASE_FILE).write_text(base + "\n", encoding="utf-8")
        return cls(repo, path, base)

    @classmethod
    def reopen(cls, repo: Path, path: Path) -> Worktree:
        """The worktree an interrupted run left at ``path``, with the base it was created at."""
        if path.resolve() not in registered_worktrees(repo):
            raise WorktreeError(f"{path} is not a registered worktree of {repo}")
        base_file = path.parent / BASE_FILE
        if not base_file.is_file():
            raise WorktreeError(f"{base_file} is missing; the worktree's base is unknown")
        return cls(repo, path, base_file.read_text(encoding="utf-8").strip())

    def cache_environment(self) -> dict[str, str]:
        """Point ccache at this worktree, so a compile hits entries another worktree made.

        Every job builds the same sources in its own worktree, and CMake passes them by
        absolute path. Without a base directory ccache keys each worktree's compiles on
        its own path: a fresh job's first build compiled every unit cold and filled the
        cache with entries no other job could use.
        """
        return {"CCACHE_BASEDIR": str(self.path), "CCACHE_NOHASHDIR": "1"}

    def capture_patch(self) -> tuple[str, list[str]]:
        """Everything the worker changed since ``base`` (commits, edits, untracked) as a patch.

        Stages in the worktree's own index; the main tree and its index are untouched.
        """
        git(self.path, "add", "-A")
        patch = git(self.path, "diff", "--cached", "--binary", self.base)
        names = git(
            self.path, "diff", "--cached", "--name-only", "-z", self.base
        ).split("\0")
        return patch, [name for name in names if name]
