#!/usr/bin/env python3
"""codemap.py: find existing definitions before writing new ones.

    codemap.py find PHRASE [PHRASE ...] [--limit N]
        Search every definition (functions, lambdas, constants, macros, types, aliases, enum
        members) in this repo, its submodules and the checkouts it links to (gitignored
        symlinks such as external/<framework> included). A phrase matches when each of its
        words matches the name, the value, or the comment above it. Numbers match by value,
        so `find 1024` also finds `= 0x400`. Phrases are alternatives. A name or constant value
        defined in more than one first-party unit is printed first as a duplicate group.

Stdlib only; run from inside the project.
"""
import argparse
import os
import re
import subprocess
import sys

CODE_EXT = {
    ".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx", ".inl", ".py", ".rs", ".go",
    ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".swift", ".rb", ".php",
    ".cs", ".m", ".mm", ".scala", ".lua", ".sh", ".zig", ".ml", ".ex", ".exs",
    ".glsl", ".frag", ".vert", ".comp", ".hlsl", ".metal",
}
SKIP_DIRS = {"build", "scratch", "node_modules", ".venv", "__pycache__", ".git"}


def _is_code(name):
    return os.path.splitext(name)[1].lower() in CODE_EXT


def _git(root, *args):
    res = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else ""


def _toplevel(path):
    return _git(path, "rev-parse", "--show-toplevel").strip() or None


# ---------------------------------------------------------------- find

def _linked_checkouts(root):
    """Git checkouts this repo reaches through submodules or symlinked directories."""
    found = []
    for line in _git(root, "submodule", "status").splitlines():
        parts = line[1:].split()
        if len(parts) >= 2:
            found.append(os.path.join(root, parts[1]))
    for dp, dirs, _ in os.walk(root):
        if dp.count(os.sep) - root.count(os.sep) >= 3:
            dirs[:] = []
            continue
        keep = []
        for d in dirs:
            full = os.path.join(dp, d)
            if d in SKIP_DIRS:
                continue
            if os.path.islink(full):
                found.append(full)
            else:
                keep.append(d)
        dirs[:] = keep
    return found


def _owner(root):
    url = _git(root, "remote", "get-url", "origin").strip()
    m = re.search(r"[:/]([^/:]+)/[^/]+?(?:\.git)?$", url)
    return m.group(1).lower() if m else None


def _search_roots(start):
    """(label, real path, ours) for the repo and every checkout it links to, nearest first.

    A checkout is ours when its origin has the same owner as the starting repo's."""
    top = _toplevel(start)
    if not top:
        sys.exit("codemap.py find: run inside a git checkout")
    owner = _owner(top)
    roots, seen, queue = [], set(), [(top, ".")]
    while queue:
        path, label = queue.pop(0)
        real = os.path.realpath(path)
        if real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        roots.append((label, real, label == "." or _owner(real) == owner))
        for link in _linked_checkouts(path):
            if _toplevel(link) != os.path.realpath(link):
                continue
            rel = os.path.relpath(link, path)
            queue.append((link, rel if label == "." else os.path.join(label, rel)))
    return roots


def _root_files(real):
    out = _git(real, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in out.split("\0"):
        if not rel or not _is_code(rel):
            continue
        if any(part in SKIP_DIRS for part in rel.split("/")[:-1]):
            continue
        full = os.path.join(real, rel)
        if os.path.isfile(full) and not os.path.islink(full):
            yield rel


_CPP_KEYWORDS = {
    "return", "if", "else", "while", "for", "switch", "case", "do", "new", "delete", "throw",
    "sizeof", "goto", "co_return", "co_await", "static_assert", "decltype", "alignof",
    "typedef", "operator",
}
_DEFS = [
    ("macro", re.compile(r"^\s*#\s*define\s+(\w+)(.*)")),
    ("type", re.compile(
        r"^\s*(?:template\s*<.*>\s*)?(?:class|struct|union|enum(?:\s+class)?|concept)"
        r"\s+(?:\[\[[^\]]*\]\]\s*)?(\w+)\s*(?:final\s*)?(?::[^;{]*)?(?:\{|$|=)")),
    ("alias", re.compile(r"^\s*using\s+(\w+)\s*=\s*(.*?);?\s*$")),
    ("alias", re.compile(r"^\s*typedef\s+.*?\b(\w+)\s*;\s*$")),
    ("lambda", re.compile(r"^\s*(?:const\s+|static\s+|constexpr\s+)*auto\s+(\w+)\s*=\s*(\[.*)")),
    ("const", re.compile(
        r"^\s*(?:(?:inline|static|extern|constinit)\s+)*(?:constexpr|const)\s+"
        r"[\w:<>,\s\*&]*?\b(\w+)\s*(?:\[[^\]]*\])*\s*[={]\s*(.*?)[;,]?\s*$")),
    ("enum", re.compile(r"^\s*(k[A-Z]\w*|[A-Z][A-Z0-9_]{2,})\s*=\s*([^,;{}()]+?)\s*,?\s*(?://.*)?$")),
    ("function", re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?((?:[\w:<>,\*&\[\]]+\s+)+)[\*&]*((?:\w+::)*~?\w+)\s*\(")),
]
_PY_DEFS = [
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")),
    ("type", re.compile(r"^\s*class\s+(\w+)")),
    ("const", re.compile(r"^([A-Z][A-Z0-9_]+)\s*(?::[^=]+)?=\s*(.+)$")),
]
_COMMENT = re.compile(r"^\s*(?://+|#(?!\s*(?:define|include|if|endif|else|pragma|undef))|/?\*+)\s?(.*)")


def _definition(line, is_py):
    for kind, pat in (_PY_DEFS if is_py else _DEFS):
        m = pat.match(line)
        if not m:
            continue
        if kind == "function" and not is_py:
            types = m.group(1).split()
            head = line.split("(")[0]
            if types[0] in _CPP_KEYWORDS or "=" in head or "&&" in head or "||" in head:
                continue
            if line.rstrip().endswith(","):
                continue
            return kind, m.group(2), ""
        value = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
        if kind == "const" and "constexpr" not in line and not re.match(r"[-\d{'\"]", value):
            continue
        return kind, m.group(1), value
    return None


def _words(name):
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.replace("::", " ").replace("_", " "))
    spaced = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", spaced)
    words = [w.lower() for w in spaced.split()]
    if len(words) > 1 and words[0] == "k":
        words = words[1:]
    return words


def _number(text):
    try:
        return int(text.replace("'", "").rstrip("uUlL"), 0)
    except ValueError:
        return None


def _numbers_in(text):
    return {_number(t) for t in re.findall(r"\b(?:0[xX][0-9a-fA-F']+|\d[\d']*)[uUlL]*\b", text)} - {None}


def _word_hits(word, name_words, joined, value_numbers, comment):
    num = _number(word)
    if num is not None:
        if num in value_numbers:
            return 2
        return 1 if num in _numbers_in(comment) else 0
    stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
    if any(w.startswith(stem) for w in name_words) or stem in joined:
        return 2
    return 1 if re.search(r"\b" + re.escape(stem), comment) else 0


def _scan(root_label, real):
    for rel in _root_files(real):
        try:
            with open(os.path.join(real, rel), encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        is_py = rel.endswith(".py")
        comment = []
        for i, line in enumerate(lines):
            c = _COMMENT.match(line)
            if c and not line.lstrip().startswith("#define"):
                comment.append(c.group(1))
                continue
            found = _definition(line, is_py)
            if found:
                kind, name, value = found
                trailing = line.split("//", 1)[1] if "//" in line else ""
                text = " ".join(comment + [trailing]).lower()
                path = rel if root_label == "." else os.path.join(root_label, rel)
                yield path, i + 1, kind, name, value, line.strip(), text
            comment = []


def _duplicates(hits):
    """First-party hits defining one multi-word name, or one value under a matching name, in
    more than one unit."""
    groups = {}
    for third_party, _, _, path, line, kind, src, name, numbers, named in hits:
        if third_party:
            continue
        words = _words(name.split("::")[-1])
        keys = [("name", "".join(words))] if len(words) > 1 else []
        if named and kind in ("const", "enum", "macro") and len(numbers) == 1 and not numbers & {0, 1}:
            keys.append(("value", next(iter(numbers))))
        for key in keys:
            groups.setdefault(key, []).append((path, line, kind, src))
    # A declaration and its definition (foo.h, foo.cpp) are one unit.
    return [members for members in groups.values()
            if len({os.path.splitext(path)[0] for path, _, _, _ in members}) > 1]


def cmd_find(args):
    phrases = [p.lower().split() for p in args.phrases]
    roots = _search_roots(os.getcwd())
    hits = []
    for order, (label, real, ours) in enumerate(roots):
        for path, line, kind, name, value, src, comment in _scan(label, real):
            name_words = _words(name)
            joined = "".join(name_words)
            numbers = _numbers_in(value)
            best = 0
            for words in phrases:
                scores = [_word_hits(w, name_words, joined, numbers, comment) for w in words]
                if all(scores):
                    best = max(best, sum(scores))
            if best:
                named = any(_number(w) is None and _word_hits(w, name_words, joined, set(), "")
                            for words in phrases for w in words)
                hits.append((not ours, -best, order, path, line, kind, src, name, numbers, named))
    hits.sort(key=lambda hit: hit[:5])
    print("searched: " + ", ".join(label + ("" if ours else " (third-party)")
                                   for label, _, ours in roots))
    if not hits:
        print("no definition matches; place new code where docs/codemap.md says this layer lives")
        return
    duplicates = _duplicates(hits)
    for members in duplicates[:5]:
        print(f"defined {len(members)} times (merge into the owner, do not add another):")
        for path, line, kind, src in members:
            print(f"  {path}:{line}  {kind:8} {src[:120]}")
    if len(duplicates) > 5:
        print(f"... {len(duplicates) - 5} more duplicate groups")
    for third_party, _, _, path, line, kind, src, _, _, _ in hits[:args.limit]:
        print(f"{path}:{line}  {kind:8} {'[3p] ' if third_party else ''}{src[:120]}")
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more (--limit)")


def main(argv=None):
    p = argparse.ArgumentParser(description="find existing definitions of a concept")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="find existing definitions of a concept")
    f.add_argument("phrases", nargs="+")
    f.add_argument("--limit", type=int, default=40)
    f.set_defaults(func=cmd_find)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
