#!/usr/bin/env python3
"""Check first-party C++ ownership rules using Clang's parsed AST.

Run this beside clang-tidy with the same Clang compile database. Formatting and
clang-tidy configuration are separate gates; this tool covers syntax that those
checks cannot reliably prohibit.
"""

import argparse
import bisect
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path


FUNCTION_KINDS = {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl"}
ENTRY_POINTS = {"main"}
CPP_SUFFIXES = {".C", ".cc", ".cpp", ".cxx", ".c++", ".mm"}
REQUIRED_TIDY_CHECKS = {
    "clang-diagnostic-*", "clang-analyzer-*", "bugprone-*", "performance-*",
    "readability-braces-around-statements",
}
REQUIRED_FORMAT_SETTINGS = {
    "AllowShortIfStatementsOnASingleLine": "Never",
    "AllowShortLoopsOnASingleLine": "false",
    "AllowShortBlocksOnASingleLine": "Never",
    "AllowShortFunctionsOnASingleLine": "None",
    "AllowShortLambdasOnASingleLine": "None",
    "InsertBraces": "true",
}


def settings(text):
    """Read scalar keys from tool-normalized configuration, not raw YAML syntax."""
    return {
        key.strip(): value.strip().strip("'\"")
        for line in text.splitlines()
        if ":" in line
        for key, value in (line.split(":", 1),)
    }


def inspect_configs(tidy_output, format_output):
    tidy = settings(tidy_output)
    formatter = settings(format_output)
    checks = {item.strip() for item in tidy.get("Checks", "").split(",")}
    findings = []
    if "-*" in checks:
        findings.append(".clang-tidy disables the default checks with -*")
    for check in sorted(REQUIRED_TIDY_CHECKS - checks):
        findings.append(f".clang-tidy does not enable {check}")
    if "-readability-braces-around-statements" in checks:
        findings.append(".clang-tidy disables readability-braces-around-statements")
    if tidy.get("WarningsAsErrors") != "*":
        findings.append(".clang-tidy must set WarningsAsErrors: '*'")
    if tidy.get("readability-braces-around-statements.ShortStatementLines") != "0":
        findings.append(".clang-tidy must set readability-braces-around-statements.ShortStatementLines: 0")
    for key, expected in REQUIRED_FORMAT_SETTINGS.items():
        if formatter.get(key) != expected:
            findings.append(f".clang-format must set {key}: {expected}")
    return findings


def audit_configs(project):
    tidy = project / ".clang-tidy"
    formatter = project / ".clang-format"
    missing = [f"missing {item.name}" for item in (tidy, formatter) if not item.is_file()]
    if missing:
        return missing
    commands = (
        ["clang-tidy", "--dump-config", f"--config-file={tidy}"],
        ["clang-format", f"--style=file:{formatter}", "--dump-config"],
    )
    outputs = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"{' '.join(command[:1])} cannot read {project}: {result.stderr.strip()}")
        outputs.append(result.stdout)
    return inspect_configs(*outputs)


def source_path(location, directory, previous):
    if not isinstance(location, dict):
        return previous, {}
    position = location.get("spellingLoc", location)
    if not isinstance(position, dict):
        return previous, {}
    name = position.get("file")
    if name:
        candidate = Path(name)
        previous = (candidate if candidate.is_absolute() else directory / candidate).resolve()
    return previous, position


def line_number(location, source, line_cache):
    if location.get("line"):
        return location["line"]
    offset = location.get("offset")
    if offset is None or source is None:
        return 0
    if source not in line_cache:
        try:
            content = source.read_bytes()
        except OSError:
            return 0
        line_cache[source] = [index for index, char in enumerate(content) if char == 10]
    return bisect.bisect_left(line_cache[source], offset) + 1


def first_party(source, root, excluded):
    if source is None or not source.is_relative_to(root):
        return False
    return not any(source == item or source.is_relative_to(item) for item in excluded)


def inspect_ast(tree, main_source, directory, root, excluded=(), allowed_globals=()):
    """Return stable (path, line, rule, symbol) findings and visited source files."""
    findings = set()
    visited = set()
    last_file = main_source
    line_cache = {}
    entry_points = ENTRY_POINTS | set(allowed_globals)

    def walk(node, ancestors):
        nonlocal last_file
        if not isinstance(node, dict):
            return
        last_file, location = source_path(node.get("loc"), directory, last_file)
        source = last_file
        kind = node.get("kind", "")
        if first_party(source, root, excluded) and location.get("offset") is not None:
            visited.add(source)
            line = line_number(location, source, line_cache)
            symbol = node.get("name", "")
            scopes = set(ancestors)
            c_boundary = "LinkageSpecDecl" in scopes
            if not node.get("isImplicit"):
                if node.get("storageClass") == "extern" and not (c_boundary and kind == "FunctionDecl"):
                    findings.add((source, line, "extern declaration", symbol))
                if kind == "FunctionDecl" and not c_boundary and symbol not in entry_points:
                    if not scopes.intersection({"NamespaceDecl", "CXXRecordDecl", "ClassTemplateDecl", "RecordDecl"}):
                        findings.add((source, line, "global-namespace function", symbol))
                if kind == "VarDecl" and scopes.intersection(FUNCTION_KINDS | {"LambdaExpr"}):
                    if node.get("storageClass") == "static":
                        findings.add((source, line, "block-scope static", symbol))
                    qualifier = node.get("type", {}).get("qualType", "")
                    if node.get("constexpr") or re.search(r"\bconst\b", qualifier):
                        findings.add((source, line, "block-scope const", symbol))
        child_ancestors = (*ancestors, kind)
        for child in node.get("inner", ()):
            walk(child, child_ancestors)

    walk(tree, ())
    return findings, visited


def compile_arguments(entry):
    if "arguments" in entry:
        arguments = list(entry["arguments"])
    elif "command" in entry:
        arguments = shlex.split(entry["command"])
    else:
        raise ValueError("compile command has neither arguments nor command")
    if not arguments:
        raise ValueError("compile command is empty")
    filtered = [arguments[0]]
    skip_next = False
    for argument in arguments[1:]:
        if skip_next:
            skip_next = False
        elif argument in {"-o", "-MF", "-MT", "-MQ", "/Fo"}:
            skip_next = True
        elif argument in {"-c", "-MMD", "-MD", "-MP"} or argument.startswith("/Fo"):
            continue
        else:
            filtered.append(argument)
    if skip_next:
        raise ValueError("compile command ends in an output or dependency option")
    return [*filtered, "-fsyntax-only", "-Xclang", "-ast-dump=json"]


def check_database(database, root, excluded=(), allowed_globals=()):
    entries = json.loads(database.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("compile database has no translation units")
    findings = set()
    visited = set()
    units = 0
    for entry in entries:
        directory = Path(entry["directory"]).resolve()
        source = Path(entry["file"])
        source = (source if source.is_absolute() else directory / source).resolve()
        if source.suffix not in CPP_SUFFIXES or not first_party(source, root, excluded):
            continue
        units += 1
        command = compile_arguments(entry)
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"AST compile failed for {source}:\n{result.stderr.strip()}")
        try:
            tree = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Clang emitted no readable AST for {source}: {error}") from error
        current, files = inspect_ast(tree, source, directory, root, excluded, allowed_globals)
        findings.update(current)
        visited.update(files)
        visited.add(source)
    if not units:
        raise ValueError("compile database has no first-party C++ translation units")
    return units, findings, visited


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--compile-commands", type=Path)
    mode.add_argument("--audit-config", type=Path, help="project directory containing .clang-tidy and .clang-format")
    parser.add_argument("--root", type=Path, help="first-party source root for AST mode")
    parser.add_argument("--exclude", action="append", type=Path, default=[], help="exact vendored/generated subtree")
    parser.add_argument("--allow-global", action="append", default=[], help="exact required platform/ABI entry point")
    arguments = parser.parse_args(argv)
    if arguments.audit_config:
        project = arguments.audit_config.resolve()
        try:
            findings = audit_configs(project)
        except (OSError, RuntimeError) as error:
            print(f"cpp_policy: {error}", file=sys.stderr)
            return 2
        print(f"cpp_policy: audited {project}, {len(findings)} configuration violations")
        for finding in findings:
            print(f"{project}: {finding}")
        return 1 if findings else 0
    if arguments.root is None:
        parser.error("--root is required with --compile-commands")
    root = arguments.root.resolve()
    excluded = [root / "build", root / ".git"]
    excluded.extend(
        (item if item.is_absolute() else root / item).resolve() for item in arguments.exclude
    )
    try:
        units, findings, visited = check_database(
            arguments.compile_commands.resolve(), root, excluded, arguments.allow_global
        )
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"cpp_policy: {error}", file=sys.stderr)
        return 2
    print(f"cpp_policy: scanned {units} translation units, {len(visited)} first-party files, {len(findings)} violations")
    for source, line, rule, symbol in sorted(findings):
        print(f"{source}:{line}: {rule}: {symbol}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
