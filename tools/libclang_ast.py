"""Parse a translation unit through the toolchain's own libclang and walk only first-party code.

A ctypes binding, so no Python package is needed: the library is the one that
ships beside the compile command's Clang driver. The walk never enters a
file-scope declaration that expands outside the caller's files, so system and
library headers are parsed once by Clang and never visited from Python.
"""

import ctypes
import ctypes.util
import functools
import re
import shutil
import subprocess
import sys
from pathlib import Path


INSTALL_HINT = (
    "install the libclang that matches this Clang: "
    "Fedora `sudo dnf install clang-libs`; Debian/Ubuntu `sudo apt install libclang1-{major}`; "
    "Arch `sudo pacman -S clang`; macOS `xcode-select --install` or `brew install llvm`; "
    "Windows `winget install LLVM.LLVM`"
)
VERSION = re.compile(r"clang version (\d+)\.")
LIBRARY_PATTERNS = ("libclang.so*", "libclang.dylib", "libclang.dll")

# CXCursorKind values from clang-c/Index.h.
STRUCT_DECL, UNION_DECL, CLASS_DECL = 2, 3, 4
FUNCTION_DECL, VAR_DECL = 8, 9
CXX_METHOD, NAMESPACE, LINKAGE_SPEC = 21, 22, 23
CONSTRUCTOR, DESTRUCTOR, CONVERSION_FUNCTION = 24, 25, 26
FUNCTION_TEMPLATE, CLASS_TEMPLATE, CLASS_TEMPLATE_PARTIAL = 30, 31, 32
LAMBDA_EXPR = 144
STORAGE_CLASSES = {2: "extern", 3: "static"}

#: Scope a cursor opens for everything beneath it.
IN_NAMESPACE_OR_RECORD = 1
IN_LINKAGE_SPEC = 2
IN_FUNCTION = 4
#: Children of this cursor are file-scope declarations, each tested for ownership.
FILE_SCOPE = 8
OPENS = {
    NAMESPACE: IN_NAMESPACE_OR_RECORD | FILE_SCOPE,
    STRUCT_DECL: IN_NAMESPACE_OR_RECORD,
    UNION_DECL: IN_NAMESPACE_OR_RECORD,
    CLASS_DECL: IN_NAMESPACE_OR_RECORD,
    CLASS_TEMPLATE: IN_NAMESPACE_OR_RECORD,
    CLASS_TEMPLATE_PARTIAL: IN_NAMESPACE_OR_RECORD,
    LINKAGE_SPEC: IN_LINKAGE_SPEC | FILE_SCOPE,
    FUNCTION_DECL: IN_FUNCTION,
    CXX_METHOD: IN_FUNCTION,
    CONSTRUCTOR: IN_FUNCTION,
    DESTRUCTOR: IN_FUNCTION,
    CONVERSION_FUNCTION: IN_FUNCTION,
    FUNCTION_TEMPLATE: IN_FUNCTION,
    LAMBDA_EXPR: IN_FUNCTION,
}
#: Containers entered even from a foreign file, since an include can reopen them.
CONTAINERS = {NAMESPACE, LINKAGE_SPEC}
#: A qualified definition such as `void n::g() {}` belongs to these though written outside them.
OWNERS = {kind for kind, opens in OPENS.items() if opens & IN_NAMESPACE_OR_RECORD}
#: Declarations whose name and storage class the rules read.
NAMED = {FUNCTION_DECL, VAR_DECL, FUNCTION_TEMPLATE}

CHILD_BREAK, CHILD_CONTINUE, CHILD_RECURSE = 0, 1, 2
DECLARATION, CODE, OTHER = "declaration", "code", "other"
SEVERITY_ERROR = 3
PARSE_ERRORS = {1: "failed", 2: "crashed", 3: "was given invalid arguments", 4: "could not read the AST"}
SHOWN_DIAGNOSTICS = 20


class Cursor(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int), ("xdata", ctypes.c_int), ("data", ctypes.c_void_p * 3)]


class Location(ctypes.Structure):
    _fields_ = [("ptr_data", ctypes.c_void_p * 2), ("int_data", ctypes.c_uint)]


class String(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("private_flags", ctypes.c_uint)]


VISITOR = ctypes.CFUNCTYPE(ctypes.c_int, Cursor, Cursor, ctypes.c_void_p)
INCLUSION_VISITOR = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(Location), ctypes.c_uint, ctypes.c_void_p)
SIGNATURES = {
    "clang_getClangVersion": ([], String),
    "clang_getCString": ([String], ctypes.c_char_p),
    "clang_disposeString": ([String], None),
    "clang_createIndex": ([ctypes.c_int, ctypes.c_int], ctypes.c_void_p),
    "clang_disposeIndex": ([ctypes.c_void_p], None),
    "clang_parseTranslationUnit2FullArgv": (
        [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int,
         ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)],
        ctypes.c_int,
    ),
    "clang_disposeTranslationUnit": ([ctypes.c_void_p], None),
    "clang_getNumDiagnostics": ([ctypes.c_void_p], ctypes.c_uint),
    "clang_getDiagnostic": ([ctypes.c_void_p, ctypes.c_uint], ctypes.c_void_p),
    "clang_getDiagnosticSeverity": ([ctypes.c_void_p], ctypes.c_int),
    "clang_formatDiagnostic": ([ctypes.c_void_p, ctypes.c_uint], String),
    "clang_defaultDiagnosticDisplayOptions": ([], ctypes.c_uint),
    "clang_disposeDiagnostic": ([ctypes.c_void_p], None),
    "clang_getTranslationUnitCursor": ([ctypes.c_void_p], Cursor),
    "clang_visitChildren": ([Cursor, VISITOR, ctypes.c_void_p], ctypes.c_uint),
    "clang_isDeclaration": ([ctypes.c_int], ctypes.c_uint),
    "clang_isExpression": ([ctypes.c_int], ctypes.c_uint),
    "clang_isStatement": ([ctypes.c_int], ctypes.c_uint),
    "clang_getCursorLocation": ([Cursor], Location),
    "clang_getCursorSpelling": ([Cursor], String),
    "clang_Cursor_getStorageClass": ([Cursor], ctypes.c_int),
    "clang_getTemplateCursorKind": ([Cursor], ctypes.c_int),
    "clang_getCursorSemanticParent": ([Cursor], Cursor),
    "clang_getSpellingLocation": (
        [Location, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
         ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)],
        None,
    ),
    "clang_getExpansionLocation": (
        [Location, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
         ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)],
        None,
    ),
    "clang_getFileName": ([ctypes.c_void_p], String),
    "clang_getInclusions": ([ctypes.c_void_p, INCLUSION_VISITOR, ctypes.c_void_p], None),
}


class LibclangMissing(RuntimeError):
    """No libclang matching the compile command's Clang could be loaded."""


class Declaration:
    """One first-party declaration with the scope it sits in."""

    __slots__ = ("kind", "name", "storage", "source", "line", "scope")

    def __init__(self, kind, name, storage, source, line, scope):
        self.kind = kind
        self.name = name
        self.storage = storage
        self.source = source
        self.line = line
        self.scope = scope


class ParsedUnit:
    """What a walk found: first-party declarations, the first-party files and every file read."""

    def __init__(self, declarations, visited, inclusions):
        self.declarations = declarations
        self.visited = visited
        self.inclusions = inclusions


def driver_major(driver):
    result = subprocess.run([driver, "--version"], capture_output=True, text=True)
    match = VERSION.search(result.stdout)
    if result.returncode or match is None:
        raise LibclangMissing(f"{driver} --version does not name a Clang version: {result.stderr.strip()}")
    return match.group(1)


def library_candidates(driver):
    """Where the driver's own toolchain keeps libclang, nearest first."""
    resolved = Path(driver).resolve()
    prefix = resolved.parent.parent
    directories = [prefix / "lib64", prefix / "lib", resolved.parent]
    result = subprocess.run([driver, "-print-resource-dir"], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        library_dir = Path(result.stdout.strip()).resolve().parents[1]
        directories += [library_dir, library_dir.parent / "lib64", library_dir.parent / "bin"]
    seen = []
    for directory in directories:
        for pattern in LIBRARY_PATTERNS:
            for path in sorted(directory.glob(pattern)):
                if path not in seen:
                    seen.append(path)
    found = ctypes.util.find_library("clang")
    if found:
        seen.append(Path(found))
    return seen


class Libclang:
    """The loaded library, with every function this tool calls typed."""

    def __init__(self, path):
        self.path = path
        self.handle = ctypes.CDLL(str(path))
        for name, (arguments, result) in SIGNATURES.items():
            function = getattr(self.handle, name)
            function.argtypes = arguments
            function.restype = result
        self.version = self.text(self.handle.clang_getClangVersion())
        self.kind_classes = {}

    def text(self, value):
        raw = self.handle.clang_getCString(value)
        self.handle.clang_disposeString(value)
        return raw.decode("utf-8", "replace") if raw else ""

    def kind_class(self, kind):
        """DECLARATION, CODE (a statement or expression) or OTHER, once per cursor kind."""
        if kind not in self.kind_classes:
            if self.handle.clang_isDeclaration(kind):
                self.kind_classes[kind] = DECLARATION
            elif self.handle.clang_isExpression(kind) or self.handle.clang_isStatement(kind):
                self.kind_classes[kind] = CODE
            else:
                self.kind_classes[kind] = OTHER
        return self.kind_classes[kind]


@functools.lru_cache(maxsize=None)
def library_for(driver):
    """The libclang of `driver`'s toolchain, refusing any other version."""
    executable = shutil.which(driver) or driver
    major = driver_major(executable)
    rejected = []
    for path in library_candidates(executable):
        try:
            library = Libclang(path)
        except (OSError, AttributeError) as error:
            rejected.append(f"{path}: {error}")
            continue
        match = VERSION.search(library.version)
        if match and match.group(1) == major:
            return library
        rejected.append(f"{path}: {library.version}")
    detail = "; ".join(rejected) if rejected else "none found"
    raise LibclangMissing(
        f"no libclang {major} beside {executable} ({detail}); " + INSTALL_HINT.format(major=major)
    )


class Walk:
    """One depth-first pass over the unit, collecting first-party declarations."""

    def __init__(self, library, directory, ours):
        self.library = library
        self.api = library.handle
        self.directory = directory
        self.ours = ours
        self.files = {}
        self.declarations = []
        self.visited = set()
        self.stack = []
        self.error = None
        self.file = ctypes.c_void_p()
        self.line = ctypes.c_uint()
        self.ignored = ctypes.c_uint()

    def path(self, handle):
        """The resolved path of a CXFile and whether it is first-party, once per file."""
        if handle not in self.files:
            name = Path(self.library.text(self.api.clang_getFileName(handle)))
            source = (name if name.is_absolute() else self.directory / name).resolve()
            self.files[handle] = (source, self.ours(source))
        return self.files[handle]

    def locate(self, function, cursor):
        function(self.api.clang_getCursorLocation(cursor), ctypes.byref(self.file),
                 ctypes.byref(self.line), ctypes.byref(self.ignored), ctypes.byref(self.ignored))
        if not self.file.value:
            return None, False, 0
        source, ours = self.path(self.file.value)
        return source, ours, self.line.value

    def visit(self, cursor, parent, _data):
        try:
            return self.step(cursor, parent)
        except BaseException as error:  # a ctypes callback cannot raise; run() re-raises
            self.error = error
            return CHILD_BREAK

    def identity(self, cursor):
        """The AST node behind a cursor; the parent declaration libclang also packs in varies by path."""
        kind_class = self.library.kind_class(cursor.kind)
        if kind_class == DECLARATION:
            return (cursor.kind, cursor.data[0])
        if kind_class == CODE:
            return (cursor.kind, cursor.data[1])
        return bytes(cursor)

    def step(self, cursor, parent):
        parent_key = self.identity(parent)
        depth = len(self.stack) - 1
        while depth >= 0 and self.stack[depth][0] != parent_key:
            depth -= 1
        if depth >= 0:
            del self.stack[depth + 1:]
        else:
            # libclang reports a lambda capture initializer's children but not the initializer.
            self.stack.append((parent_key, self.stack[-1][1]))
        scope = self.stack[-1][1]
        kind = cursor.kind
        if scope & FILE_SCOPE and kind not in CONTAINERS:
            _, ours, _ = self.locate(self.api.clang_getExpansionLocation, cursor)
            if not ours:
                return CHILD_CONTINUE
        if self.library.kind_class(kind) == DECLARATION:
            source, ours, line = self.locate(self.api.clang_getSpellingLocation, cursor)
            if ours:
                self.visited.add(source)
                if kind in NAMED:
                    self.record(cursor, kind, source, line, scope)
        self.stack.append((self.identity(cursor), (scope & ~FILE_SCOPE) | OPENS.get(kind, 0)))
        return CHILD_RECURSE

    def record(self, cursor, kind, source, line, scope):
        if kind == FUNCTION_TEMPLATE:
            if self.api.clang_getTemplateCursorKind(cursor) != FUNCTION_DECL:
                return
            kind = FUNCTION_DECL
        if not scope & IN_NAMESPACE_OR_RECORD and self.api.clang_getCursorSemanticParent(cursor).kind in OWNERS:
            scope |= IN_NAMESPACE_OR_RECORD
        name = self.library.text(self.api.clang_getCursorSpelling(cursor))
        storage = STORAGE_CLASSES.get(self.api.clang_Cursor_getStorageClass(cursor), "")
        self.declarations.append(Declaration(
            "function" if kind == FUNCTION_DECL else "variable", name, storage, source, line,
            scope & ~FILE_SCOPE,
        ))

    def run(self, unit):
        root = self.api.clang_getTranslationUnitCursor(unit)
        self.stack.append((self.identity(root), FILE_SCOPE))
        self.api.clang_visitChildren(root, VISITOR(self.visit), None)
        if self.error is not None:
            raise self.error


def inclusions(library, unit, directory):
    """Every file the unit read, the main file included."""
    files = set()

    def visit(handle, _stack, _depth, _data):
        name = Path(library.text(library.handle.clang_getFileName(handle)))
        files.add((name if name.is_absolute() else directory / name).resolve())

    library.handle.clang_getInclusions(unit, INCLUSION_VISITOR(visit), None)
    return files


def errors(library, unit):
    api = library.handle
    options = api.clang_defaultDiagnosticDisplayOptions()
    found = []
    for index in range(api.clang_getNumDiagnostics(unit)):
        diagnostic = api.clang_getDiagnostic(unit, index)
        try:
            if api.clang_getDiagnosticSeverity(diagnostic) >= SEVERITY_ERROR:
                found.append(library.text(api.clang_formatDiagnostic(diagnostic, options)))
        finally:
            api.clang_disposeDiagnostic(diagnostic)
    return found


def parse(arguments, directory, source, ours):
    """Parse one unit with its compile arguments and walk its first-party declarations.

    `arguments[0]` is the Clang driver; `ours(path)` says whether a file is first-party.
    """
    if not source.is_file():
        raise RuntimeError(f"{source} is in the compile database but does not exist; reconfigure the build")
    library = library_for(arguments[0])
    api = library.handle
    argv = [*arguments, f"-working-directory={directory}"]
    encoded = (ctypes.c_char_p * len(argv))(*(item.encode(sys.getfilesystemencoding()) for item in argv))
    index = api.clang_createIndex(0, 0)
    unit = ctypes.c_void_p()
    try:
        code = api.clang_parseTranslationUnit2FullArgv(
            index, None, encoded, len(argv), None, 0, 0, ctypes.byref(unit)
        )
        if code or not unit.value:
            raise RuntimeError(f"libclang {PARSE_ERRORS.get(code, f'returned {code}')} parsing {source}")
        try:
            failures = errors(library, unit)
            if failures:
                shown = "\n".join(failures[:SHOWN_DIAGNOSTICS])
                raise RuntimeError(f"AST compile failed for {source}:\n{shown}")
            walk = Walk(library, directory, ours)
            walk.run(unit)
            return ParsedUnit(walk.declarations, walk.visited, inclusions(library, unit, directory))
        finally:
            api.clang_disposeTranslationUnit(unit)
    finally:
        api.clang_disposeIndex(index)
