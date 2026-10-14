#!/usr/bin/env python3
"""Check first-party C++ ownership rules using Clang's parsed AST.

Run this beside clang-tidy with the same Clang compile database. Formatting and
clang-tidy configuration are separate gates; this tool covers syntax that those
checks cannot reliably prohibit.
"""

import argparse
import concurrent.futures
import concurrent.futures.process
import ctypes
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import libclang_ast
from unit_cache import UnitCache


TOOL_SOURCES = tuple(Path(__file__).resolve().parent / name
                     for name in ("cpp_policy.py", "libclang_ast.py", "unit_cache.py"))
#: Per-unit results live beside the compile database, inside the build directory.
CACHE_DIRECTORY = "cpp_policy_cache"
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
    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        value = raw.strip()
        if value.startswith('"') and value.endswith('"'):
            value = json.loads(value)
        else:
            value = value.strip("'")
        values[key.strip()] = value
    return values


def short_functions_disabled(format_output, formatter):
    value = formatter.get("AllowShortFunctionsOnASingleLine")
    if value in {"None", "false"}:
        return True
    if value != "":
        return False
    lines = format_output.splitlines()
    for index, line in enumerate(lines):
        if line != "AllowShortFunctionsOnASingleLine:":
            continue
        children = {}
        for child in lines[index + 1:]:
            if child and not child[0].isspace():
                break
            if ":" in child:
                key, child_value = child.split(":", 1)
                children[key.strip()] = child_value.strip()
        return all(children.get(key) == "false" for key in ("Empty", "Inline", "Other"))
    return False


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
        if key == "AllowShortFunctionsOnASingleLine":
            valid = short_functions_disabled(format_output, formatter)
        else:
            valid = formatter.get(key) == expected
        if not valid:
            findings.append(f".clang-format must set {key}: {expected} (effective: {formatter.get(key)!r})")
    return findings


def audit_configs(project):
    tidy = project / ".clang-tidy"
    formatter = project / ".clang-format"
    missing = [f"missing {item.name}" for item in (tidy, formatter) if not item.is_file()]
    if missing:
        return missing
    commands = (
        [os.environ.get("CLANG_TIDY", "clang-tidy"), "--dump-config", f"--config-file={tidy}"],
        [os.environ.get("CLANG_FORMAT", "clang-format"), f"--style=file:{formatter}", "--dump-config"],
    )
    outputs = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"{' '.join(command[:1])} cannot read {project}: {result.stderr.strip()}")
        outputs.append(result.stdout)
    return inspect_configs(*outputs)


def within(source, paths):
    return any(source == item or source.is_relative_to(item) for item in paths)


def first_party(source, root, excluded):
    if source is None or not source.is_relative_to(root):
        return False
    return not within(source, excluded)


def unit_findings(declarations, allowed_globals=(), entry_roots=(), references=(), retired=()):
    """The ownership rules over one unit's first-party declarations and references."""
    entry_points = ENTRY_POINTS | set(allowed_globals)
    findings = set()
    # A retired name has an owner that composes it; a harness under an entry root may still drive it.
    for item in references:
        if item.name in retired and not within(item.source, entry_roots):
            findings.add((item.source, item.line, "retired name", item.name))
    for item in declarations:
        c_boundary = bool(item.scope & libclang_ast.IN_LINKAGE_SPEC)
        if item.storage == "extern" and not (c_boundary and item.kind == "function"):
            findings.add((item.source, item.line, "extern declaration", item.name))
        if item.kind == "function" and not c_boundary and not item.scope & libclang_ast.IN_NAMESPACE_OR_RECORD:
            if item.name in ENTRY_POINTS and entry_roots and not within(item.source, entry_roots):
                findings.add((item.source, item.line, "entry point", item.name))
            elif item.name not in entry_points:
                findings.add((item.source, item.line, "global-namespace function", item.name))
        # A function-local `static` is hidden state with an owner nobody named; a
        # local `const` or `constexpr` is not, so only the storage class is a finding.
        if item.kind == "variable" and item.scope & libclang_ast.IN_FUNCTION and item.storage == "static":
            findings.add((item.source, item.line, "block-scope static", item.name))
    return findings


COMPILER_LAUNCHERS = frozenset({"ccache", "sccache"})
#: A GCC command is parsed by the libclang of the matching Clang driver.
GCC_DRIVER = re.compile(r"^(?:[\w.]+-)?(?P<name>g\+\+|gcc|c\+\+|cc)(?:-[\d.]+)?$")


def without_launcher(arguments, search_path=None):
    """The compile arguments with a caching launcher replaced by the compiler it wraps.

    libclang parses the command in-process, so it needs the compiler itself, not its wrapper.
    """
    program = Path(arguments[0])
    if program.stem in COMPILER_LAUNCHERS:
        return arguments[1:]
    if program.parent.name not in COMPILER_LAUNCHERS:
        return arguments
    # A masquerade link such as /usr/lib64/ccache/clang++: the same name on PATH, past the link.
    directories = (search_path if search_path is not None else os.environ.get("PATH", "")).split(os.pathsep)
    rest = os.pathsep.join(d for d in directories if d and Path(d).name not in COMPILER_LAUNCHERS)
    compiler = shutil.which(program.name, path=rest)
    if compiler is None:
        raise ValueError(f"no {program.name} on PATH behind the launcher {program}")
    return [compiler, *arguments[1:]]


def clang_driver(arguments, search_path=None):
    """The compile arguments with a GCC driver replaced by the matching Clang driver."""
    match = GCC_DRIVER.match(Path(arguments[0]).name)
    if match is None:
        return arguments
    name = "clang" if match.group("name") in {"gcc", "cc"} else "clang++"
    compiler = shutil.which(name, path=search_path)
    if compiler is None:
        raise ValueError(f"no {name} on PATH to parse a {arguments[0]} compile command")
    return [compiler, *arguments[1:]]


def compile_arguments(entry):
    if "arguments" in entry:
        arguments = list(entry["arguments"])
    elif "command" in entry:
        arguments = split_compile_command(entry["command"])
    else:
        raise ValueError("compile command has neither arguments nor command")
    if not arguments:
        raise ValueError("compile command is empty")
    arguments = without_launcher(arguments)
    if not arguments:
        raise ValueError("compile command is only a launcher")
    arguments = clang_driver(arguments)
    filtered = [arguments[0]]
    skip_next = False
    for argument in arguments[1:]:
        if skip_next:
            skip_next = False
        elif argument in {"-o", "-MF", "-MT", "-MQ", "/Fo", "/Fd"}:
            skip_next = True
        elif argument in {"-c", "/c", "--", "-MMD", "-MD", "-MP"} or argument.startswith(("/Fo", "/Fd")):
            continue
        else:
            filtered.append(argument)
    if skip_next:
        raise ValueError("compile command ends in an output or dependency option")
    return filtered


def split_compile_command(command):
    """Preserve Windows paths and quoted arguments from CMake's command string."""
    if os.name != "nt":
        return shlex.split(command)
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    arguments = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not arguments:
        raise OSError("CommandLineToArgvW could not parse the compile command")
    try:
        return [arguments[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(arguments, ctypes.c_void_p))


#: Options naming an include search directory, joined (`-Idir`) or as the next argument.
SEARCH_OPTIONS = ("-iquote", "-isystem", "-idirafter", "-I", "/I")


def search_directories(arguments, directory):
    """Every include search directory a compile command names, resolved against its directory."""
    found = []
    pending = False
    for argument in arguments[1:]:
        if pending:
            found.append(argument)
            pending = False
        elif argument in SEARCH_OPTIONS:
            pending = True
        else:
            found.extend(argument[len(option):] for option in SEARCH_OPTIONS[:4]
                         if argument.startswith(option) and len(argument) > len(option))
    return {(directory / path).resolve() for path in found}


def watched_directories(arguments, directory, read, root, excluded):
    """The first-party directories where a new file can change what a unit's parse finds.

    Its include search directories, and the directory of every first-party file it read, which
    quoted includes search first. A directory inside another watched one is covered by it.
    """
    candidates = {path for path in search_directories(arguments, directory) if first_party(path, root, excluded)}
    candidates.update(path.parent for path in read if first_party(path, root, excluded))
    watched = []
    for path in sorted(candidates):
        if not within(path, watched):
            watched.append(path)
    return watched


def unit_source(entry):
    directory = Path(entry["directory"]).resolve()
    source = Path(entry["file"])
    return directory, (source if source.is_absolute() else directory / source).resolve()


def check_unit(arguments, directory, source, root, excluded, allowed_globals=(), entry_roots=(), retired=()):
    """Scan one translation unit: its findings, first-party files, every file read, and when."""
    started = time.time_ns()
    parsed = libclang_ast.parse(arguments, directory, source, lambda path: first_party(path, root, excluded), retired)
    findings = unit_findings(parsed.declarations, allowed_globals, entry_roots, parsed.references, retired)
    return findings, parsed.visited | {source}, parsed.inclusions, started


def scan_workers(units):
    """How many units to scan at once.

    Each unit is parsed and walked in its own worker process: the walk runs
    Python per declaration, so threads would take turns on one interpreter.
    """
    override = os.environ.get("CPP_POLICY_JOBS")
    if override:
        try:
            wanted = int(override)
        except ValueError:
            raise ValueError(f"CPP_POLICY_JOBS is not a number: {override!r}") from None
        if wanted < 1:
            raise ValueError(f"CPP_POLICY_JOBS must be at least 1, not {wanted}")
        return min(wanted, units)
    return max(1, min(units, os.cpu_count() or 1))


def policy_salt(root, excluded, allowed_globals, entry_roots, retired=()):
    """Everything besides the unit itself that a cached result depends on."""
    tools = hashlib.sha256(b"".join(path.read_bytes() for path in TOOL_SOURCES)).hexdigest()
    return [tools, str(root), sorted(map(str, excluded)), sorted(allowed_globals), sorted(map(str, entry_roots)),
            sorted(retired)]


def encode_result(findings, visited):
    return {
        "findings": sorted([str(source), line, rule, symbol] for source, line, rule, symbol in findings),
        "visited": sorted(str(path) for path in visited),
    }


def check_database(database, root, excluded=(), allowed_globals=(), entry_roots=(), retired=()):
    """Scan every first-party unit, reusing cached results; (units, reused, findings, visited)."""
    entries = json.loads(database.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("compile database has no translation units")
    wanted = []
    for entry in entries:
        _, source = unit_source(entry)
        if source.suffix in CPP_SUFFIXES and first_party(source, root, excluded):
            wanted.append(entry)
    if not wanted:
        raise ValueError("compile database has no first-party C++ translation units")
    cache_directory = database.parent / CACHE_DIRECTORY
    cache = UnitCache(
        cache_directory,
        policy_salt(root, excluded, allowed_globals, entry_roots, retired),
        lambda path: path.name != ".git" and path != cache_directory and first_party(path, root, excluded),
    )
    results = []
    pending = []
    for entry in wanted:
        directory, source = unit_source(entry)
        arguments = compile_arguments(entry)
        library = libclang_ast.library_for(arguments[0])
        # One source can be compiled into several targets with different flags.
        unit = [str(directory), str(source), entry.get("output") or arguments]
        key = cache.key(unit, arguments, str(library.path), library.version)
        cached = cache.load(unit, key)
        if cached is None:
            pending.append((unit, key, arguments, directory, source))
        else:
            results.append(cached)
    if pending:
        with concurrent.futures.ProcessPoolExecutor(max_workers=scan_workers(len(pending))) as pool:
            futures = [
                (item, pool.submit(check_unit, item[2], item[3], item[4], root, excluded, allowed_globals, entry_roots,
                                   retired))
                for item in pending
            ]
            try:
                for (unit, key, arguments, directory, source), future in futures:
                    try:
                        findings, visited, read, started = future.result()
                    except concurrent.futures.process.BrokenProcessPool as error:
                        raise RuntimeError(f"the scan process for {source} died: {error}") from error
                    result = encode_result(findings, visited)
                    watched = watched_directories(arguments, directory, read, root, excluded)
                    cache.store(unit, key, result, read, watched, started)
                    results.append(result)
            except BaseException:
                pool.shutdown(cancel_futures=True)
                raise
    findings = set()
    visited = set()
    for result in results:
        findings.update((Path(source), line, rule, symbol) for source, line, rule, symbol in result["findings"])
        visited.update(Path(path) for path in result["visited"])
    return len(wanted), len(wanted) - len(pending), findings, visited


def accepted_sites(path):
    """Read a project's accepted ownership sites: `file:rule:symbol` per line.

    No line number: a site keeps its meaning when the file above it changes,
    and a list that goes stale on every edit gets regenerated instead of read.
    """
    sites = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(f"{path}:{number}: expected 'file:rule:symbol', got {line.strip()!r}")
        sites.add(tuple(part.strip() for part in parts))
    return sites


def apply_accepted(findings, root, accepted):
    """Split findings into the ones still to answer for and the accepted ones.

    An accepted site that no longer occurs comes back as a violation of its own.
    An allowance nobody removes when the code improves is how a gate quietly
    stops covering the thing it was written for.
    """
    remaining = []
    matched = set()
    for source, line, rule, symbol in findings:
        named = str(source.relative_to(root)) if source.is_relative_to(root) else str(source)
        site = (named, rule, symbol)
        if site in accepted:
            matched.add(site)
        else:
            remaining.append((source, line, rule, symbol))
    return remaining, sorted(accepted - matched)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--compile-commands", type=Path)
    mode.add_argument("--audit-config", type=Path, help="project directory containing .clang-tidy and .clang-format")
    parser.add_argument("--root", type=Path, help="first-party source root for AST mode")
    parser.add_argument("--exclude", action="append", type=Path, default=[], help="exact vendored/generated subtree")
    parser.add_argument("--allow-global", action="append", default=[], help="exact required platform/ABI entry point")
    parser.add_argument("--entry-root", action="append", type=Path, default=[],
                        help="file or subtree where `main` may live; once given, `main` anywhere else is a finding")
    parser.add_argument("--retired-name", action="append", default=[],
                        help="global function a first-party file outside the entry roots may no longer use")
    parser.add_argument("--accept", type=Path, help="file listing accepted 'path:rule:symbol' ownership sites")
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
    entry_roots = [(item if item.is_absolute() else root / item).resolve() for item in arguments.entry_root]
    try:
        units, reused, findings, visited = check_database(
            arguments.compile_commands.resolve(), root, excluded, arguments.allow_global, entry_roots,
            arguments.retired_name
        )
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"cpp_policy: {error}", file=sys.stderr)
        return 2
    stale = []
    accepted = 0
    if arguments.accept:
        try:
            sites = accepted_sites(arguments.accept.resolve())
        except (OSError, ValueError) as error:
            print(f"cpp_policy: {error}", file=sys.stderr)
            return 2
        remaining, stale = apply_accepted(findings, root, sites)
        accepted = len(findings) - len(remaining)
        findings = remaining
    summary = (f"cpp_policy: scanned {units} translation units ({reused} unchanged since the last scan), "
               f"{len(visited)} first-party files")
    if arguments.accept:
        summary += f", {accepted} accepted sites"
    print(f"{summary}, {len(findings) + len(stale)} violations")
    for source, line, rule, symbol in sorted(findings):
        print(f"{source}:{line}: {rule}: {symbol}")
    for named, rule, symbol in stale:
        print(f"{arguments.accept}: accepted site no longer occurs: {named}:{rule}:{symbol}")
    return 1 if findings or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
