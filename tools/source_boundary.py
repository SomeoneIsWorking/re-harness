#!/usr/bin/env python3
"""Apply a project's data-owned source-boundary policy to its tracked working tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from typing import Any


INCLUDE_LINE = re.compile(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", re.MULTILINE)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load policy manifest {path}: {error}") from error
    required = {
        "source_suffixes",
        "source_names",
        "excluded_roots",
        "excluded_paths",
        "forbidden_tokens",
        "forbidden_include_fragments",
        "forbidden_path_components",
        "allowed_shell_paths",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"policy manifest {path} is missing keys: {', '.join(missing)}")
    for key in required:
        if not isinstance(data[key], list) or not all(isinstance(item, str) for item in data[key]):
            raise ValueError(f"policy manifest {path} key {key} must be a string list")
    return data


def tracked_paths(root: Path) -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z", "--", "."],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = [PurePosixPath(raw.decode()) for raw in result.stdout.split(b"\0") if raw]
    return [path for path in paths if (root / path).exists()]


def is_excluded(path: PurePosixPath, manifest: Mapping[str, Any]) -> bool:
    return str(path) in manifest["excluded_paths"] or (
        bool(path.parts) and path.parts[0] in manifest["excluded_roots"]
    )


def is_live_source(path: PurePosixPath, manifest: Mapping[str, Any]) -> bool:
    return not is_excluded(path, manifest) and (
        path.name in manifest["source_names"] or path.suffix in manifest["source_suffixes"]
    )


def inspect_tree(
    paths: Iterable[PurePosixPath],
    contents: Mapping[PurePosixPath, str],
    manifest: Mapping[str, Any],
) -> list[str]:
    violations: list[str] = []
    for path in sorted(paths, key=str):
        if is_excluded(path, manifest):
            continue
        forbidden_components = set(path.parts) & set(manifest["forbidden_path_components"])
        for component in sorted(forbidden_components):
            violations.append(f"{path}: forbidden path component {component}")
        if path.suffix == ".sh" and str(path) not in manifest["allowed_shell_paths"]:
            violations.append(f"{path}: non-allowed shell tool")
        if not is_live_source(path, manifest):
            continue
        text = contents.get(path, "")
        for token in manifest["forbidden_tokens"]:
            if token in text:
                violations.append(f"{path}: forbidden source token {token}")
        for include in INCLUDE_LINE.findall(text):
            for fragment in manifest["forbidden_include_fragments"]:
                if fragment in include:
                    violations.append(f"{path}: forbidden include fragment {fragment}")
    return violations


def read_live_sources(
    root: Path, paths: Iterable[PurePosixPath], manifest: Mapping[str, Any]
) -> dict[PurePosixPath, str]:
    return {
        path: (root / path).read_text(encoding="utf-8")
        for path in paths
        if is_live_source(path, manifest) and (root / path).is_file()
    }


def selftest(manifest: Mapping[str, Any]) -> int:
    clean = PurePosixPath("game/clean.cpp")
    fixtures: dict[PurePosixPath, str] = {clean: '#include "native_dispatch.h"\n'}
    for index, token in enumerate(manifest["forbidden_tokens"]):
        fixtures[PurePosixPath(f"game/token_{index}.cpp")] = token
    for index, fragment in enumerate(manifest["forbidden_include_fragments"]):
        fixtures[PurePosixPath(f"game/include_{index}.cpp")] = f'#include "{fragment}bad.h"\n'
    for index, component in enumerate(manifest["forbidden_path_components"]):
        fixtures[PurePosixPath(f"{component}/path_{index}.cpp")] = ""
    fixtures[PurePosixPath("tools/disallowed.sh")] = "#!/bin/sh\n"

    violations = inspect_tree(fixtures, fixtures, manifest)
    expected = (
        len(manifest["forbidden_tokens"])
        + len(manifest["forbidden_include_fragments"])
        + len(manifest["forbidden_path_components"])
        + 1
    )
    clean_violations = inspect_tree([clean], fixtures, manifest)
    if clean_violations or len(violations) != expected:
        print(
            f"SOURCE BOUNDARY SELFTEST FAIL: expected {expected}, got {len(violations)}",
            file=sys.stderr,
        )
        return 1
    print(f"SOURCE BOUNDARY SELFTEST PASS: rejected {expected} negative fixtures")
    return 0


def main(default_root: Path | None = None, default_manifest: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.root is None or args.manifest is None:
        parser.error("--root and --manifest are required")
    root = args.root.resolve()
    manifest_path = args.manifest.resolve()
    try:
        manifest = load_manifest(manifest_path)
    except ValueError as error:
        print(f"SOURCE BOUNDARY ERROR: {error}", file=sys.stderr)
        return 2
    if args.selftest:
        return selftest(manifest)
    try:
        paths = tracked_paths(root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"SOURCE BOUNDARY ERROR: cannot enumerate {root}: {error}", file=sys.stderr)
        return 2
    violations = inspect_tree(paths, read_live_sources(root, paths, manifest), manifest)
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    scanned = sum(is_live_source(path, manifest) for path in paths)
    print(f"SOURCE BOUNDARY PASS: scanned {scanned} live files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
