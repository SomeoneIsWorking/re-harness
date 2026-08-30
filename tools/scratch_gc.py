#!/usr/bin/env python3
"""Scoped garbage collector for per-project ``<repo>/scratch`` trees.

Agents write logs, frame dumps, screenshots, and build caches under a project's
gitignored ``scratch/`` directory. Those artifacts are disposable but accumulate
into tens of gigabytes. This tool removes stale scratch files safely:

* A target named ``scratch`` inside ``~/repo`` (any depth) is GC'd directly. Any
  other directory under (or equal to) ``~/repo`` is treated as a search root and
  every ``scratch`` directory beneath it is GC'd. Everything else is refused.
  Override the root with ``--repo-root``.
* It is dry-run by default; ``--apply`` is required to delete anything.
* It only removes regular files whose mtime is older than ``--days`` (default 14),
  then prunes directories that became empty. Symlinks are unlinked, never followed.
* ``--keep GLOB`` (repeatable) protects matching relative paths.
* It always prints what it scanned, what matched, and what it skipped -- a run
  that deletes nothing says so explicitly rather than looking like a no-op.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import time
from pathlib import Path

GIB = 1073741824


def human(size: int) -> str:
    return f"{size / GIB:.2f} GiB" if size >= GIB else f"{size / 1048576:.1f} MiB"


def resolve_targets(raw: str, repo_root: Path) -> list[Path]:
    target = Path(raw).resolve()
    if not target.is_dir():
        raise ValueError(f"{raw} is not a directory")
    if target != repo_root and repo_root not in target.parents:
        raise ValueError(f"{target} is not under {repo_root}; refusing")
    if target.name == "scratch":
        if target.parent == repo_root:
            raise ValueError(f"{target} has no project directory between it and {repo_root}; refusing")
        return [target]
    found = sorted(
        d for d in target.rglob("scratch")
        if d.is_dir() and not d.is_symlink() and d.parent != repo_root
    )
    # Keep only the top-most scratch of each nested chain (a scratch inside a
    # scratch, or one a build tree mirrored under an absolute path, is covered
    # by its ancestor).
    top = [d for d in found if not any(a in d.parents for a in found)]
    if not top:
        raise ValueError(f"no 'scratch' directories found under {target}")
    return top


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scratch-gc", description=__doc__)
    parser.add_argument("targets", nargs="+",
                        help="scratch directories, or roots to search for scratch dirs (e.g. ~/repo)")
    parser.add_argument("--days", type=float, default=14.0, help="remove files older than N days (default 14)")
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument("--keep", action="append", default=[], metavar="GLOB",
                        help="protect relative paths matching GLOB (repeatable)")
    parser.add_argument("--repo-root", default=str(Path.home() / "repo"),
                        help="directory scratch trees must live under (default ~/repo)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    cutoff = time.time() - args.days * 86400

    try:
        seen: set[Path] = set()
        targets: list[Path] = []
        for raw in args.targets:
            for scratch in resolve_targets(raw, repo_root):
                if scratch not in seen:
                    seen.add(scratch)
                    targets.append(scratch)
    except ValueError as exc:
        print(f"scratch-gc: {exc}", file=sys.stderr)
        return 2

    grand_removed = 0
    for scratch in targets:
        scanned = scanned_bytes = matched = removed_bytes = kept_recent = protected = 0
        to_remove: list[Path] = []
        for path in sorted(scratch.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            scanned += 1
            rel = path.relative_to(scratch).as_posix()
            try:
                st = path.lstat()
            except OSError:
                continue
            scanned_bytes += st.st_size
            if any(fnmatch.fnmatch(rel, pat) for pat in args.keep):
                protected += 1
                continue
            if st.st_mtime >= cutoff:
                kept_recent += 1
                continue
            matched += 1
            removed_bytes += st.st_size
            to_remove.append(path)

        verb = "removing" if args.apply else "would remove"
        print(f"\n{scratch}")
        print(f"  scanned  {scanned} files ({human(scanned_bytes)})")
        print(f"  kept     {kept_recent} newer than {args.days:g}d, {protected} protected by --keep")
        if not to_remove:
            print(f"  {verb}  nothing (no files older than {args.days:g}d)")
            continue
        print(f"  {verb}  {matched} files ({human(removed_bytes)})")

        if not args.apply:
            grand_removed += removed_bytes
            continue

        for path in to_remove:
            try:
                path.unlink()
            except OSError as exc:
                print(f"  ! {path}: {exc}", file=sys.stderr)
        for path in sorted(scratch.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
        grand_removed += removed_bytes

    print(f"\nscratch-gc: {'freed' if args.apply else 'would free'} {human(grand_removed)} across {len(targets)} tree(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
