"""Project-document and issue-catalog sources used by info.py brief."""

import os
import subprocess
import sys
import textwrap


DOCUMENTS = (
    ("PROJECT GOALS", ("docs/project-goals.md", "PROJECT-GOALS.md", "GOALS.md")),
    ("PROJECT STATE", ("docs/project-state.md", "PROJECT-STATE.md", "STATUS.md")),
    ("CODEMAP", ("docs/codemap.md", "docs/code-map.md")),
    ("RE-FRONTIER", ("docs/re-frontier.md",)),
)


def _run(command, root):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, cwd=root)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _grep_file(root, relpath, words, limit=3):
    """Search one registry file, including untracked worktree edits."""
    path = os.path.join(root, relpath)
    try:
        with open(path, encoding="utf-8") as source:
            lines = source.read().splitlines()
    except OSError as exc:
        return [f"could not read {relpath}: {exc}"]
    lowered = [word.lower() for word in words]
    hits = []
    for lineno, line in enumerate(lines, 1):
        if any(word in line.lower() for word in lowered):
            hits.append(f"{relpath}:{lineno}:{line}")
            if len(hits) == limit:
                break
    return hits


def emit_external_sources(root, skills, words):
    """Print issue and project-document sections for an information brief."""
    query = " ".join(words)
    catalog = os.path.join(skills, "issue-catalog", "catalog.py")
    issues_dir = os.path.join(root, "docs", "issues")
    if os.path.exists(catalog) and os.path.isdir(issues_dir):
        output = _run([sys.executable, catalog, "search", query], root)
        if output:
            print("\n  ISSUES (atomic work / symptom -> cause / dead end)")
            print(textwrap.indent("\n".join(output.splitlines()[:8]), "    "))
        else:
            count = len([name for name in os.listdir(issues_dir) if name.endswith(".md")])
            print(f"\n  ISSUES: no match across {count} entr(ies) in docs/issues")
    elif os.path.exists(catalog):
        print("\n  ISSUES: docs/issues does not exist here, so the issue "
              "catalog was NOT consulted -- this is not an empty result")

    for label, candidates in DOCUMENTS:
        relpath = next(
            (candidate for candidate in candidates if os.path.exists(os.path.join(root, candidate))),
            None,
        )
        if not relpath:
            print(f"\n  {label}: none of {', '.join(candidates)} exists here, so it was NOT "
                  "consulted — this is not an empty result")
            continue
        hits = _grep_file(root, relpath, words)
        print(f"\n  {label} ({relpath})")
        body = "\n".join(hits) if hits else f"(no line matches any of: {', '.join(words)})"
        print(textwrap.indent(body, "    "))

    local = [
        tracker for tracker in ("tools/kanban.py", "tools/findings.py")
        if os.path.exists(os.path.join(root, tracker))
    ]
    if local:
        print(f"\n  PROJECT-LOCAL TRACKERS present: {', '.join(local)} — query them too.")
