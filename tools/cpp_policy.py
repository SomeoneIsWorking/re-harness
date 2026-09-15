#!/usr/bin/env python3
"""Check first-party C++ ownership rules using Clang's parsed AST.

Run this beside clang-tidy with the same Clang compile database. Formatting and
clang-tidy configuration are separate gates; this tool covers syntax that those
checks cannot reliably prohibit.
"""

import argparse
import bisect
import concurrent.futures
import ctypes
import json
import os
import re
import shlex
import subprocess
import sys
import threading
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
#: The keys a rule reads. Everything else in a node is stepped over unparsed,
#: which is most of the document: a `type` or `range` object costs nothing here.
RECORDED_KEYS = {"kind", "loc", "name", "storageClass", "isImplicit"}
JSON_SPACE = re.compile(r"\s+")
JSON_KEY = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:')
JSON_MARKER = re.compile(r'["{}\[\]]')
JSON_STRING_MARKER = re.compile(r'["\\]')
JSON_SCALAR = re.compile(r"[^,\]}\s]+")


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


def source_path(location, directory, previous, resolved):
    """The file a node sits in, carried forward when Clang omits an unchanged one.

    `resolved` memoizes the path work. Resolving a name touches the filesystem
    and a translation unit names the same few hundred files tens of millions of
    times, so doing it once per name rather than once per node is most of what
    makes this scan finish.
    """
    if not isinstance(location, dict):
        return previous, {}
    position = location.get("spellingLoc", location)
    if not isinstance(position, dict):
        return previous, {}
    name = position.get("file")
    if name:
        if name not in resolved:
            candidate = Path(name)
            resolved[name] = (candidate if candidate.is_absolute() else directory / candidate).resolve()
        previous = resolved[name]
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


class AstRecorder:
    """Keep only rule findings and source provenance while visiting AST nodes."""

    def __init__(self, main_source, directory, root, excluded, allowed_globals):
        self.findings = set()
        self.visited = set()
        self.last_file = main_source
        self.directory = directory
        self.root = root
        self.excluded = excluded
        self.entry_points = ENTRY_POINTS | set(allowed_globals)
        self.line_cache = {}
        self.resolved = {}
        self.ours = {}

    def record(self, node, ancestors):
        self.last_file, location = source_path(
            node.get("loc"), self.directory, self.last_file, self.resolved
        )
        source = self.last_file
        kind = node.get("kind", "")
        if source not in self.ours:
            self.ours[source] = first_party(source, self.root, self.excluded)
        if self.ours[source] and location.get("offset") is not None:
            self.visited.add(source)
            line = line_number(location, source, self.line_cache)
            symbol = node.get("name", "")
            c_boundary = "LinkageSpecDecl" in ancestors
            if not node.get("isImplicit"):
                if node.get("storageClass") == "extern" and not (c_boundary and kind == "FunctionDecl"):
                    self.findings.add((source, line, "extern declaration", symbol))
                if kind == "FunctionDecl" and not c_boundary and symbol not in self.entry_points:
                    if not ancestors.intersection({"NamespaceDecl", "CXXRecordDecl", "ClassTemplateDecl", "RecordDecl"}):
                        self.findings.add((source, line, "global-namespace function", symbol))
                # A function-local `static` is hidden state with an owner nobody
                # named: its lifetime, its initialization order, and its sharing
                # between callers are all invisible at the call site. An ordinary
                # local `const` or `constexpr` is none of those things — it is the
                # recommended way to write a local — so only the storage class is
                # a finding here.
                if kind == "VarDecl" and ancestors.intersection(FUNCTION_KINDS | {"LambdaExpr"}):
                    if node.get("storageClass") == "static":
                        self.findings.add((source, line, "block-scope static", symbol))


class JsonStream:
    """Read Clang's AST as tokens, holding only the bytes a rule asks for.

    One translation unit's JSON runs to hundreds of megabytes, so nothing here
    loops over characters: every scan is a single regular-expression search
    across a whole buffer, and the interpreter is asked to act once per token
    instead of once per byte. Measured on a real port, that is the difference
    between reading a unit in seconds and in minutes. Only the current buffer is
    held, so a unit of any size still fits in memory.
    """

    CHUNK = 1 << 20

    def __init__(self, source):
        self.source = source
        self.buffer = ""
        self.position = 0
        #: While a value is being captured, consumed text stays in the buffer so
        #: the whole span can be handed to the C JSON parser in one piece.
        self.holding = False

    def refill(self):
        chunk = self.source.read(self.CHUNK)
        if not chunk:
            return False
        if self.holding:
            self.buffer += chunk
        else:
            self.buffer = self.buffer[self.position:] + chunk
            self.position = 0
        return True

    def ensure(self, count):
        """Hold at least `count` characters, so a short token cannot straddle."""
        while len(self.buffer) - self.position < count:
            if not self.refill():
                return

    def find(self, pattern):
        """The next match of `pattern`, reading more input until one appears."""
        while True:
            match = pattern.search(self.buffer, self.position)
            if match is not None:
                return match
            self.position = len(self.buffer)
            if not self.refill():
                return None

    def peek(self):
        while self.position == len(self.buffer):
            if not self.refill():
                return ""
        return self.buffer[self.position]

    def take(self):
        char = self.peek()
        if char:
            self.position += 1
        return char

    def space(self):
        while True:
            if self.position == len(self.buffer) and not self.refill():
                return
            match = JSON_SPACE.match(self.buffer, self.position)
            if match is None:
                return
            self.position = match.end()

    def expect(self, expected):
        self.space()
        actual = self.take()
        if actual != expected:
            raise ValueError(f"malformed Clang AST JSON: expected {expected!r}, got {actual!r}")

    def string_body(self):
        """Consume a string whose opening quote is already taken."""
        while True:
            match = self.find(JSON_STRING_MARKER)
            if match is None:
                raise ValueError("truncated Clang AST JSON string")
            self.position = match.end()
            if match.group() == '"':
                return
            if not self.take():
                raise ValueError("truncated Clang AST JSON escape")

    def container(self):
        """Consume an object or array whose opening bracket is still ahead."""
        depth = 0
        while True:
            match = self.find(JSON_MARKER)
            if match is None:
                raise ValueError("unterminated Clang AST JSON container")
            marker = match.group()
            self.position = match.end()
            if marker == '"':
                self.string_body()
            elif marker in "{[":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return

    def scalar_body(self):
        while True:
            self.ensure(64)
            match = JSON_SCALAR.match(self.buffer, self.position)
            if match is None or match.end() < len(self.buffer):
                if match is not None:
                    self.position = match.end()
                return
            self.position = match.end()
            if not self.refill():
                return

    def skip(self):
        """Step over one value without building anything from it."""
        self.space()
        marker = self.peek()
        if marker == '"':
            self.take()
            self.string_body()
        elif marker and marker in "{[":
            self.container()
        elif marker:
            self.scalar_body()

    def value(self):
        """The next value, parsed from its own text by the C JSON decoder."""
        self.space()
        start = self.position
        self.holding = True
        try:
            self.skip()
            text = self.buffer[start:self.position]
        finally:
            self.holding = False
        if not text:
            raise ValueError("malformed Clang AST JSON value")
        return json.loads(text)

    def key(self):
        """The next object key and its colon.

        Clang writes plain identifiers, so one anchored match takes the key and
        the colon together; anything else falls back to a full string read.
        """
        self.space()
        self.ensure(256)
        match = JSON_KEY.match(self.buffer, self.position)
        if match is not None:
            self.position = match.end()
            return match.group(1)
        self.expect('"')
        start = self.position - 1
        self.holding = True
        try:
            self.string_body()
            text = self.buffer[start:self.position]
        finally:
            self.holding = False
        self.expect(":")
        return json.loads(text)


def inspect_ast_stream(source, main_source, directory, root, excluded=(), allowed_globals=()):
    """Return findings and visited files from a bounded-memory Clang JSON stream."""
    stream = JsonStream(source)
    recorder = AstRecorder(main_source, directory, root, excluded, allowed_globals)

    def walk(ancestors):
        stream.expect("{")
        node = {}
        recorded = False
        stream.space()
        if stream.peek() == "}":
            stream.take()
            recorder.record(node, ancestors)
            return
        while True:
            key = stream.key()
            if key == "inner":
                recorder.record(node, ancestors)
                recorded = True
                stream.expect("[")
                stream.space()
                if stream.peek() != "]":
                    child_ancestors = ancestors | {node.get("kind", "")}
                    while True:
                        stream.space()
                        if stream.peek() == "{":
                            walk(child_ancestors)
                        else:
                            stream.skip()
                        stream.space()
                        if stream.peek() != ",":
                            break
                        stream.take()
                stream.expect("]")
            elif key in RECORDED_KEYS:
                if recorded:
                    raise ValueError("Clang AST metadata followed child nodes")
                node[key] = stream.value()
            else:
                stream.skip()
            stream.space()
            marker = stream.take()
            if marker == "}":
                if not recorded:
                    recorder.record(node, ancestors)
                return
            if marker != ",":
                raise ValueError("malformed Clang AST JSON node")

    walk(frozenset())
    stream.space()
    if stream.peek():
        raise ValueError("Clang AST JSON has trailing content")
    return recorder.findings, recorder.visited


def compile_arguments(entry):
    if "arguments" in entry:
        arguments = list(entry["arguments"])
    elif "command" in entry:
        arguments = split_compile_command(entry["command"])
    else:
        raise ValueError("compile command has neither arguments nor command")
    if not arguments:
        raise ValueError("compile command is empty")
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
    return [*filtered, "-fsyntax-only", "-Xclang", "-ast-dump=json"]


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


def check_unit(entry, root, excluded, allowed_globals):
    """Scan one translation unit, returning its findings and the files it saw."""
    directory = Path(entry["directory"]).resolve()
    source = Path(entry["file"])
    source = (source if source.is_absolute() else directory / source).resolve()
    command = compile_arguments(entry)
    process = subprocess.Popen(
        command, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    stderr_tail = []

    def drain_stderr():
        while chunk := process.stderr.read(65536):
            stderr_tail.append(chunk)
            if len(stderr_tail) > 2:
                stderr_tail.pop(0)

    stderr_reader = threading.Thread(target=drain_stderr)
    stderr_reader.start()
    try:
        findings, files = inspect_ast_stream(
            process.stdout, source, directory, root, excluded, allowed_globals
        )
    except (ValueError, json.JSONDecodeError) as error:
        if process.poll() is None:
            process.kill()
        returncode = process.wait()
        stderr_reader.join()
        if returncode and stderr_tail:
            raise RuntimeError(
                f"AST compile failed for {source}:\n{''.join(stderr_tail).strip()}"
            ) from error
        raise RuntimeError(f"Clang emitted no readable AST for {source}: {error}") from error
    finally:
        process.stdout.close()
    returncode = process.wait()
    stderr_reader.join()
    if returncode:
        raise RuntimeError(f"AST compile failed for {source}:\n{''.join(stderr_tail).strip()}")
    return findings, files | {source}


def scan_workers(units):
    """How many units to scan at once.

    Clang parses each unit in a child process, but reading the AST it prints is
    this tool's real cost: measured on a real port, the Python side held one core
    at full tilt while every clang child sat blocked on a full pipe. So the units
    are scanned in separate *processes* rather than threads — threads share one
    interpreter and would take turns on exactly the work that is slow. A project's
    verifier runs this on every change, and one core turned that port's seventeen
    units into ten minutes.
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


def check_database(database, root, excluded=(), allowed_globals=()):
    entries = json.loads(database.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("compile database has no translation units")
    wanted = []
    for entry in entries:
        directory = Path(entry["directory"]).resolve()
        source = Path(entry["file"])
        source = (source if source.is_absolute() else directory / source).resolve()
        if source.suffix in CPP_SUFFIXES and first_party(source, root, excluded):
            wanted.append(entry)
    if not wanted:
        raise ValueError("compile database has no first-party C++ translation units")
    findings = set()
    visited = set()
    with concurrent.futures.ProcessPoolExecutor(max_workers=scan_workers(len(wanted))) as pool:
        futures = [
            pool.submit(check_unit, entry, root, excluded, allowed_globals) for entry in wanted
        ]
        for future in futures:
            current, files = future.result()
            findings.update(current)
            visited.update(files)
    return len(wanted), findings, visited


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
    try:
        units, findings, visited = check_database(
            arguments.compile_commands.resolve(), root, excluded, arguments.allow_global
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
    summary = f"cpp_policy: scanned {units} translation units, {len(visited)} first-party files"
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
