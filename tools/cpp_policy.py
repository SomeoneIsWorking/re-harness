#!/usr/bin/env python3
"""Check first-party C++ ownership rules using Clang's parsed AST.

Run this beside clang-tidy with the same Clang compile database. Formatting and
clang-tidy configuration are separate gates; this tool covers syntax that those
checks cannot reliably prohibit.
"""

import argparse
import bisect
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
JSON_SPACE = re.compile(r"\s+")
JSON_STRING_MARKER = re.compile(r'["\\]')
JSON_SCALAR_END = re.compile(r"[,\]}\s]")


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


def top_level_const(qualified_type):
    """Distinguish a const object/pointer from a pointer or reference to const."""
    without_templates = []
    template_depth = 0
    for char in qualified_type:
        if char == "<":
            template_depth += 1
        elif char == ">" and template_depth:
            template_depth -= 1
        elif not template_depth:
            without_templates.append(char)
    spelling = "".join(without_templates)
    if "&" in spelling:
        return False
    pointer = spelling.rfind("*")
    object_suffix = spelling[pointer + 1:] if pointer >= 0 else spelling
    if pointer >= 0:
        object_suffix = object_suffix.split(")", 1)[0]
    return re.search(r"\bconst\b", object_suffix) is not None


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

    def record(self, node, ancestors):
        self.last_file, location = source_path(node.get("loc"), self.directory, self.last_file)
        source = self.last_file
        kind = node.get("kind", "")
        if first_party(source, self.root, self.excluded) and location.get("offset") is not None:
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
                if kind == "VarDecl" and ancestors.intersection(FUNCTION_KINDS | {"LambdaExpr"}):
                    if node.get("storageClass") == "static":
                        self.findings.add((source, line, "block-scope static", symbol))
                    type_info = node.get("type", {})
                    qualifier = type_info.get("desugaredQualType", type_info.get("qualType", ""))
                    if node.get("constexpr") or top_level_const(qualifier):
                        self.findings.add((source, line, "block-scope const", symbol))


class JsonStream:
    """Parse Clang's large AST incrementally without retaining child subtrees."""

    def __init__(self, source):
        self.source = source
        self.buffer = ""
        self.position = 0

    def peek(self):
        while self.position == len(self.buffer):
            self.buffer = self.source.read(65536)
            self.position = 0
            if not self.buffer:
                return ""
        return self.buffer[self.position]

    def take(self):
        char = self.peek()
        if char:
            self.position += 1
        return char

    def space(self):
        while self.peek():
            match = JSON_SPACE.match(self.buffer, self.position)
            if match is None:
                return
            self.position = match.end()

    def expect(self, expected):
        self.space()
        actual = self.take()
        if actual != expected:
            raise ValueError(f"malformed Clang AST JSON: expected {expected!r}, got {actual!r}")

    def string(self, capture=True):
        self.expect('"')
        raw = ['"'] if capture else None
        while True:
            if not self.peek():
                raise ValueError("truncated Clang AST JSON string")
            match = JSON_STRING_MARKER.search(self.buffer, self.position)
            if match is None:
                if raw is not None:
                    raw.append(self.buffer[self.position:])
                self.position = len(self.buffer)
                continue
            end = match.start()
            if raw is not None:
                raw.append(self.buffer[self.position:end + 1])
            marker = self.buffer[end]
            self.position = end + 1
            if marker == '"':
                return json.loads("".join(raw)) if raw is not None else None
            escaped = self.take()
            if not escaped:
                raise ValueError("truncated Clang AST JSON escape")
            if raw is not None:
                raw.append(escaped)

    def scalar(self, capture=True):
        self.space()
        if self.peek() == '"':
            return self.string(capture)
        chars = []
        while self.peek():
            match = JSON_SCALAR_END.search(self.buffer, self.position)
            end = len(self.buffer) if match is None else match.start()
            if capture:
                chars.append(self.buffer[self.position:end])
            self.position = end
            if match is not None:
                break
        if not chars:
            if capture:
                raise ValueError("malformed Clang AST JSON scalar")
            return None
        return json.loads("".join(chars))

    def object(self):
        self.expect("{")
        result = {}
        self.space()
        if self.peek() == "}":
            self.take()
            return result
        while True:
            key = self.string()
            self.expect(":")
            result[key] = self.value()
            self.space()
            marker = self.take()
            if marker == "}":
                return result
            if marker != ",":
                raise ValueError("malformed Clang AST JSON object")

    def value(self):
        self.space()
        if self.peek() == "{":
            return self.object()
        return self.scalar()

    def skip(self):
        self.space()
        marker = self.peek()
        if marker == '"':
            self.string(capture=False)
        elif marker and marker in "{[":
            end = "}" if marker == "{" else "]"
            self.take()
            self.space()
            if self.peek() == end:
                self.take()
                return
            while True:
                self.skip()
                self.space()
                separator = self.take()
                if separator == end:
                    return
                if separator not in {",", ":"}:
                    raise ValueError("malformed Clang AST JSON container")
        else:
            self.scalar(capture=False)


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
            key = stream.string()
            stream.expect(":")
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
            elif key in {"kind", "loc", "name", "type", "storageClass", "constexpr", "isImplicit"}:
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
            current, files = inspect_ast_stream(
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
