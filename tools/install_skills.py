#!/usr/bin/env python3
"""Install this repository's skills into supported agent skill roots."""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
DESTINATIONS = (Path(".agents/skills"), Path(".codex/skills"), Path(".claude/skills"))


def skill_name(skill_file):
    text = skill_file.read_text(encoding="utf-8")
    match = re.search(r"^name:\s*['\"]?([a-z0-9-]+)", text, re.MULTILINE)
    if not match:
        raise ValueError(f"{skill_file}: frontmatter has no valid name")
    return match.group(1)


def discover():
    found = {}
    for skill_file in sorted(SKILLS.glob("*/*/SKILL.md")):
        name = skill_name(skill_file)
        if name in found:
            raise ValueError(f"duplicate skill name {name}: {found[name]} and {skill_file.parent}")
        if skill_file.parent.name != name:
            raise ValueError(f"{skill_file.parent}: directory name does not match skill name {name}")
        found[name] = skill_file.parent.resolve()
    if not found:
        raise ValueError(f"no skills found under {SKILLS}")
    return found


def destinations(home):
    return tuple((home / relative).resolve() for relative in DESTINATIONS)


def points_to(target, source):
    return target.is_symlink() and target.resolve() == source


def safe_replace(target, expected_name, allowed_parents):
    if target.parent.resolve() not in allowed_parents or target.name != expected_name:
        raise ValueError(f"refusing out-of-scope replacement: {target}")
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    if target.is_dir():
        skill_file = target / "SKILL.md"
        if not skill_file.is_file() or skill_name(skill_file) != expected_name:
            raise ValueError(f"refusing to replace unrelated directory: {target}")
        shutil.rmtree(target)
        return
    raise ValueError(f"refusing unknown filesystem object: {target}")


def install(home, replace):
    skills = discover()
    roots = destinations(home)
    changed = 0
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
        for name, source in skills.items():
            target = root / name
            if points_to(target, source):
                continue
            if target.exists() or target.is_symlink():
                if not replace:
                    print(f"COLLISION {target} (use --replace after reviewing it)")
                    continue
                safe_replace(target, name, set(roots))
            relative = os.path.relpath(source, target.parent)
            target.symlink_to(relative, target_is_directory=True)
            print(f"LINK {target} -> {relative}")
            changed += 1
    print(f"install-skills: {len(skills)} skill(s) across {len(roots)} root(s); {changed} link(s) changed")
    return check(home)


def check(home):
    skills = discover()
    roots = destinations(home)
    problems = []
    for root in roots:
        for name, source in skills.items():
            target = root / name
            if not points_to(target, source):
                state = "missing" if not (target.exists() or target.is_symlink()) else "not canonical"
                problems.append(f"{target}: {state}; expected {source}")
    print(
        f"install-skills check: {len(skills)} skill(s) x {len(roots)} root(s) = "
        f"{len(skills) * len(roots)} link(s); {len(problems)} problem(s)"
    )
    for problem in problems:
        print(f"  ERROR {problem}")
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="link categorized skills into agent homes")
    parser.add_argument("--home", type=Path, default=Path.home(),
                        help="home directory to populate (default: current user's home)")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--replace", action="store_true",
                                help="replace only same-named skill directories/symlinks")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve()
    try:
        if args.command == "install":
            return install(home, args.replace)
        return check(home)
    except ValueError as exc:
        print(f"install-skills: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
