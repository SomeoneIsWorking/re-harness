#!/usr/bin/env python3
"""Validate docs/project-state.md and its goal/issue references."""

import argparse
import os
import re
import sys
from pathlib import Path

STATES = {"verified", "partial", "blocked", "missing"}
STATE_ID = re.compile(r"\bS\d+[a-z]?\b")
GOAL_ID = re.compile(r"\bG\d+\b")


def section(text, heading, level):
    marker = "#" * level
    match = re.search(
        rf"^{re.escape(marker)} {re.escape(heading)}\s*$\n(.*?)(?=^{re.escape(marker)} |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else ""


def detail_sections(text):
    matches = list(re.finditer(r"^### (S\d+[a-z]?)\b.*$", text, re.MULTILINE))
    details = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        details[match.group(1)] = text[match.end():end]
    return details


def table_rows(text):
    rows = {}
    for line in text.splitlines():
        if not re.match(r"^\|\s*S\d+[a-z]?\s*\|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"state row must have 5 cells: {line}")
        sid, capability, state, dependencies, goals = cells
        if sid in rows:
            raise ValueError(f"duplicate state ID {sid}")
        rows[sid] = {
            "capability": capability,
            "state": state,
            "dependencies": dependencies,
            "goals": goals,
        }
    return rows


def goal_ids(path):
    if not path.is_file():
        return set()
    return set(re.findall(r"^## (G\d+)\b", path.read_text(encoding="utf-8"), re.MULTILINE))


def issue_refs(path):
    refs = []
    if not path.is_dir():
        return refs
    for issue in sorted(path.glob("*.md")):
        for line in issue.read_text(encoding="utf-8").splitlines():
            if line.startswith("state_items:"):
                refs.extend((issue, sid) for sid in STATE_ID.findall(line))
                break
    return refs


def check(root):
    state_path = root / "docs" / "project-state.md"
    if not state_path.is_file():
        print(f"project-state: {state_path} does not exist; checked nothing")
        return 2

    text = state_path.read_text(encoding="utf-8")
    problems = []
    try:
        rows = table_rows(text)
    except ValueError as exc:
        print(f"project-state: {exc}")
        return 1
    if not rows:
        print("project-state: capability table contains no S IDs; checked nothing")
        return 2

    details = detail_sections(text)
    goals = goal_ids(root / "docs" / "project-goals.md")
    for sid, row in rows.items():
        state = row["state"]
        if state not in STATES:
            problems.append(f"{sid}: invalid state {state!r}; expected {', '.join(sorted(STATES))}")
        for dependency in STATE_ID.findall(row["dependencies"]):
            if dependency not in rows:
                problems.append(f"{sid}: unknown dependency {dependency}")
        for goal in GOAL_ID.findall(row["goals"]):
            if goal not in goals:
                problems.append(f"{sid}: unknown goal {goal}")
        detail = details.get(sid, "")
        if not detail:
            problems.append(f"{sid}: missing detail section")
        elif state == "verified" and "Evidence:" not in detail:
            problems.append(f"{sid}: verified without Evidence:")
        elif state == "partial" and not re.search(r"\bGaps?:", detail):
            problems.append(f"{sid}: partial without Gap:/Gaps:")
        elif state == "blocked" and not re.search(r"\bBlockers?:", detail):
            problems.append(f"{sid}: blocked without Blocker:/Blockers:")
        elif state == "missing" and not re.search(r"\b(?:Missing|Required) capability:", detail):
            problems.append(f"{sid}: missing without Missing capability:/Required capability:")

    focus = section(text, "Current focus", 2)
    focus_ids = sorted(set(STATE_ID.findall(focus)))
    if len(focus_ids) == 0 and re.search(r"\bnone\b", focus, re.IGNORECASE):
        pass
    elif len(focus_ids) != 1:
        problems.append(
            f"current focus must name exactly one state ID or explicitly say none; found {focus_ids}"
        )
    elif focus_ids[0] not in rows:
        problems.append(f"current focus references unknown state ID {focus_ids[0]}")

    refs = issue_refs(root / "docs" / "issues")
    for issue, sid in refs:
        if sid not in rows:
            problems.append(f"{issue.relative_to(root)}: unknown state item {sid}")

    print(
        f"project-state: checked {len(rows)} state item(s), {len(goals)} goal(s), "
        f"and {len(refs)} issue link(s); {len(problems)} problem(s)"
    )
    for problem in problems:
        print(f"  ERROR {problem}")
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="validate project goals/state/issue links")
    parser.add_argument("--root", type=Path, default=Path(os.getcwd()))
    args = parser.parse_args(argv)
    return check(args.root.resolve())


if __name__ == "__main__":
    sys.exit(main())
