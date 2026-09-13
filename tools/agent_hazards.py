#!/usr/bin/env python3
"""Mechanically detect the agent hazards that prose rules keep losing to.

Three rules in the shared instructions are exact, repeatedly broken, and
invisible to review: never `pkill`/`pgrep -f` a shared binary name (the pattern
matches the shell running the command, which is why agents have killed their own
tool mid-run), keep run artifacts in the repo's `scratch/` rather than `/tmp`,
and keep machine-specific home paths out of tracked files.

Prose alone does not hold these, so they are checked here instead. The corpus is
`git ls-files` in a repository, which is exact and cheap, and a directory walk
otherwise. An empty corpus is refused: "scanned 0 files, found 0 problems" is
the failure this tool exists to prevent, so it says so and exits 2.

A line that is correct in context can be exempted with `# hazard-ok: <reason>`,
which keeps the exemption visible at the site instead of in a config file.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The trap: -f/-x match the whole command line, which includes the shell that is
# running the very command doing the matching.
SELF_MATCH = re.compile(r"\b(pkill|pgrep)\s+(-[a-zA-Z]*[fx]|--full|--exact)|\bkillall\s+\w")
# `/tmp/` as a path root, not the `tmp` directory of something else: the
# preceding character must not be part of a longer name, so `scratch/tmp/` — the
# layout this rule asks for — does not fire.
TMP_PATH = re.compile(r"(?<![A-Za-z0-9_.])/tmp/")
HOME_PATH = re.compile(r"/home/[a-z][a-z0-9_-]*/")

TEXT_SUFFIXES = {
    ".py", ".sh", ".bash", ".zsh", ".ts", ".js", ".dart", ".c", ".cc", ".cpp",
    ".h", ".hpp", ".md", ".json", ".yaml", ".yml", ".toml", ".gradle", ".cmake",
    ".txt", ".cfg", ".ini", ".rules", ".lua",
}

# The safe-kill skill exists to document and avoid the trap, so its own text is
# the one place the pattern must be allowed to appear.
ALWAYS_ALLOW = ("skills/global/safe-kill/", "tools/safekill")

EXEMPTION = re.compile(r"#\s*hazard-ok:\s*\S+")


class Finding:
    def __init__(self, path: str, line: int, rule: str, text: str) -> None:
        self.path = path
        self.line = line
        self.rule = rule
        self.text = text.strip()

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text[:110]}"


def corpus(root: Path) -> tuple[list[Path], str]:
    """The files to scan, and how they were chosen (reported either way)."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.parts]
        return files, "directory walk (not a git repository)"
    names = [n for n in listing.stdout.decode("utf-8", "replace").split("\0") if n]
    return [root / n for n in names], "git ls-files"


def scan(root: Path, allow: list[str]) -> tuple[list[Finding], int, str]:
    files, source = corpus(root)
    findings: list[Finding] = []
    scanned = 0
    for path in files:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.as_posix()
        if path.suffix not in TEXT_SUFFIXES:
            continue
        if any(relative.startswith(prefix) or prefix in relative for prefix in ALWAYS_ALLOW):
            continue
        if any(relative.startswith(prefix) for prefix in allow):
            continue
        try:
            content = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        for number, raw in enumerate(content.splitlines(), start=1):
            if EXEMPTION.search(raw):
                continue
            # A mention in prose ("never run pkill -f") is a rule, not a hazard.
            stripped = raw.strip()
            if stripped.startswith(("*", "-", "|")) and "`" in stripped and SELF_MATCH.search(raw):
                continue
            if SELF_MATCH.search(raw):
                findings.append(Finding(relative, number, "self-matching process kill", stripped))
            if TMP_PATH.search(raw):
                findings.append(Finding(relative, number, "run artifact in /tmp", stripped))
            if HOME_PATH.search(raw):
                findings.append(Finding(relative, number, "machine-specific home path", stripped))
    return findings, scanned, source


def selftest() -> int:
    """Prove the check fires on a hazard and stays silent on clean input."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "good.py").write_text(
            'OUT = "scratch/tmp/run.log"\n'      # the repository's own layout
            'cmd = "kill -TERM $PID"\n'          # killing by PID is the remedy
        )
        report, scanned, _ = scan(root, [])
        assert scanned == 1, scanned
        assert not report, f"clean file produced findings: {report}"

        (root / "bad.sh").write_text(
            "pkill -f reload_host.py\n"
            "LOG=/tmp/run.log\n"
            "SRC=/home/someone/project/file\n"
            "# pkill -f allowed here # hazard-ok: documents the trap\n"
        )
        report, _, _ = scan(root, [])
        rules = sorted({f.rule for f in report})
        assert rules == [
            "machine-specific home path",
            "run artifact in /tmp",
            "self-matching process kill",
        ], rules
        assert len(report) == 3, [str(f) for f in report]

        # An empty corpus must be refused, never reported as clean.
        empty = root / "empty"
        empty.mkdir()
        try:
            scan(empty, [])
        except Exception:  # pragma: no cover - the CLI refuses instead
            pass
        print("agent_hazards selftest: hazards fire, clean input stays silent, exemptions hold")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository or directory to scan")
    parser.add_argument("--allow", action="append", default=[], help="relative path prefix to skip")
    parser.add_argument("--selftest", action="store_true", help="prove the checks fire on real hazards")
    arguments = parser.parse_args(argv)
    if arguments.selftest:
        return selftest()
    root = arguments.root.resolve()
    if not root.is_dir():
        print(f"agent_hazards: refused — {root} is not a directory", file=sys.stderr)
        return 2
    findings, scanned, source = scan(root, arguments.allow)
    if scanned == 0:
        print(
            f"agent_hazards: refused — no scannable files under {root} "
            f"(corpus: {source}); an empty scan proves nothing",
            file=sys.stderr,
        )
        return 2
    print(f"agent_hazards: scanned {scanned} files via {source}, {len(findings)} findings")
    for finding in sorted(findings, key=lambda f: (f.path, f.line, f.rule)):
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
