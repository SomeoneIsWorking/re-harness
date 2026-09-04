#!/usr/bin/env python3
"""Link this repository's global instructions, skills, and tools into agent homes."""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
INSTRUCTIONS = REPO / "instructions" / "AGENTS.md"
SKILL_DESTINATIONS = (Path(".agents/skills"), Path(".codex/skills"), Path(".claude/skills"))
INSTRUCTION_DESTINATIONS = (
    Path(".agents/AGENTS.md"),
    Path(".codex/AGENTS.md"),
    Path(".claude/CLAUDE.md"),
    Path("repo/AGENTS.md"),
)
TOOL_NAMES = (
    "catalog.py",
    "cleanup-files",
    "codemap.py",
    "go_public.py",
    "info.py",
    "project_state.py",
    "re_frontier.py",
    "safekill",
    "scratch_gc.py",
)
TOOL_DESTINATIONS = (Path(".agents/bin"), Path(".codex/bin"), Path(".claude/bin"))


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


def skill_destinations(home):
    return tuple((home / relative).resolve() for relative in SKILL_DESTINATIONS)


def instruction_destinations(home):
    return tuple(home / relative for relative in INSTRUCTION_DESTINATIONS)


def tool_destinations(home):
    return tuple((home / relative).resolve() for relative in TOOL_DESTINATIONS)


def points_to(target, source):
    return target.is_symlink() and target.resolve() == source


def managed_skill_link(target):
    if not target.is_symlink():
        return False
    try:
        target.resolve(strict=False).relative_to(SKILLS.resolve())
    except ValueError:
        return False
    return True


def stale_skill_links(root, skills):
    if not root.is_dir():
        return ()
    current = {name: source.resolve() for name, source in skills.items()}
    return tuple(
        target
        for target in root.iterdir()
        if managed_skill_link(target)
        and (target.name not in current or target.resolve(strict=False) != current[target.name])
    )


def link_file(target, source, replace, allowed_parents):
    target.parent.mkdir(parents=True, exist_ok=True)
    if points_to(target, source):
        return 0
    if target.exists() or target.is_symlink():
        if not replace:
            print(f"COLLISION {target} (use --replace after reviewing it)")
            return 0
        safe_replace(target, target.name, allowed_parents)
    relative = os.path.relpath(source, target.parent)
    target.symlink_to(relative)
    print(f"LINK {target} -> {relative}")
    return 1


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
    roots = skill_destinations(home)
    changed = 0
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
        for target in stale_skill_links(root, skills):
            target.unlink()
            print(f"UNLINK stale canonical skill {target}")
            changed += 1
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

    instruction_targets = instruction_destinations(home)
    instruction_parents = {target.parent.resolve() for target in instruction_targets}
    for target in instruction_targets:
        changed += link_file(target, INSTRUCTIONS.resolve(), replace, instruction_parents)

    tool_roots = tool_destinations(home)
    for root in tool_roots:
        root.mkdir(parents=True, exist_ok=True)
        for name in TOOL_NAMES:
            changed += link_file(root / name, (REPO / "tools" / name).resolve(), replace, set(tool_roots))

    print(
        f"install-global: {len(skills)} skill(s), {len(instruction_targets)} instruction link(s), "
        f"and {len(TOOL_NAMES)} tool(s) across {len(tool_roots)} bin root(s); "
        f"{changed} link(s) changed"
    )
    return check(home)


def check(home):
    skills = discover()
    roots = skill_destinations(home)
    problems = []
    for root in roots:
        for target in stale_skill_links(root, skills):
            problems.append(f"{target}: stale canonical skill link")
        for name, source in skills.items():
            target = root / name
            if not points_to(target, source):
                state = "missing" if not (target.exists() or target.is_symlink()) else "not canonical"
                problems.append(f"{target}: {state}; expected {source}")

    instruction_targets = instruction_destinations(home)
    for target in instruction_targets:
        if not points_to(target, INSTRUCTIONS.resolve()):
            state = "missing" if not (target.exists() or target.is_symlink()) else "not canonical"
            problems.append(f"{target}: {state}; expected {INSTRUCTIONS.resolve()}")

    tool_roots = tool_destinations(home)
    for root in tool_roots:
        for name in TOOL_NAMES:
            target = root / name
            source = (REPO / "tools" / name).resolve()
            if not points_to(target, source):
                state = "missing" if not (target.exists() or target.is_symlink()) else "not canonical"
                problems.append(f"{target}: {state}; expected {source}")
    print(
        f"install-global check: {len(skills) * len(roots)} skill link(s), "
        f"{len(instruction_targets)} instruction link(s), and "
        f"{len(TOOL_NAMES) * len(tool_roots)} tool link(s); {len(problems)} problem(s)"
    )
    for problem in problems:
        print(f"  ERROR {problem}")
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="link global instructions, skills, and tools into agent homes")
    parser.add_argument("--home", type=Path, default=Path.home(),
                        help="home directory to populate (default: current user's home)")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--replace", action="store_true",
                                help="replace only known instruction, skill, and tool targets")
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
