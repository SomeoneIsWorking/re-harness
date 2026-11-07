#!/usr/bin/env python3
"""Collapse AI credits in a GitHub repo's history to one Claude co-author on its first commit.

  ai_credit.py scan <name>...        count AI credits in each repo, without changing anything
  ai_credit.py rewrite <name>...     rewrite, force-push and disclose each repo, then move clones
                                     (--no-disclose for forks, whose README is upstream's)
  ai_credit.py disclose <name>...    add the AI disclosure line to each repo's README and push

``rewrite`` works on a fresh mirror of ``github.com/<owner>/<name>`` under
``~/repo/scratch/ai-credit/``. In the user's commits and in commits an AI tool authored it removes
every AI ``Co-authored-by`` trailer, makes an AI author or committer the user, and gives the first
commit ``Co-Authored-By: Claude <noreply@anthropic.com>``. It edits raw commit objects, so other
people's commits (upstream history in forks and imports) stay byte-identical, signatures included,
unless a commit of the user's sits below them. Submodule links to repos rewritten earlier are
remapped through their saved commit maps, so rewrite dependencies first.

After pushing it moves each local branch of every clone whose ``origin`` is the repo to its
rewritten commit. File contents never change, only messages, identities and submodule links, so
checkouts and uncommitted work are untouched. Commits never pushed are rewritten on top.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import zlib
from pathlib import Path

OWNER = "SomeoneIsWorking"
USER_NAME = b"Bar\xc4\xb1\xc5\x9f Hamil"
USER_EMAIL = b"barishamil90@gmail.com"
CLAUDE_TRAILER = b"Co-Authored-By: Claude <noreply@anthropic.com>"
DISCLOSURE = "Built with AI assistance (Claude and other LLMs)."
WORK = Path.home() / "repo" / "scratch" / "ai-credit"
MAPS = WORK / "maps"

# Every AI identity found in the user's repos on 2026-11-07, matched on the email.
AI_EMAIL = re.compile(
    rb"@(anthropic\.com|openai\.com|opencode\.ai|pi\.dev|earendil[.-]works|various-llms\.invalid)$"
    rb"|^(opencode|ox-alpha)@|^(pi|agent)@localhost$|@spacebunny$"
    rb"|^copilot@github\.com$|Copilot@users\.noreply\.github\.com$|^685f4c1d-", re.IGNORECASE)
# Trailers some tools wrote without an email, such as "opencode (glm-5.3-flash)".
AI_NAME = re.compile(rb"^(opencode|ox-alpha|pi|claude|codex|openai)\b", re.IGNORECASE)
TRAILER = re.compile(rb"^co-authored-by:\s*(.*)$", re.IGNORECASE)
# Copilot's bot authored upstream commits in imported histories; those stay theirs.
FOREIGN_BOT = re.compile(rb"copilot-swe-agent", re.IGNORECASE)


def refuse(message: str) -> None:
    print("ai_credit: " + message, file=sys.stderr)
    sys.exit(2)


def is_ai(email: bytes) -> bool:
    return bool(AI_EMAIL.search(email))


def is_ai_credit(value: bytes) -> bool:
    """A co-author value, "Name <email>" or a bare name, that names an AI tool."""
    email = re.search(rb"<([^>]*)>?", value)
    return is_ai(email.group(1)) if email else bool(AI_NAME.match(value.strip()))


def is_ai_trailer(line: bytes) -> bool:
    match = TRAILER.match(line.strip())
    return match is not None and is_ai_credit(match.group(1))


def owned(author_email: bytes, author_name: bytes) -> bool:
    if author_email.lower() == USER_EMAIL:
        return True
    return is_ai(author_email) and not FOREIGN_BOT.search(author_name)


def clean_message(message: bytes, first: bool) -> bytes | None:
    """The message without AI trailers (plus Claude's on the first commit); None if unchanged."""
    lines = message.split(b"\n")
    kept = [line for line in lines if not is_ai_trailer(line)]
    if len(kept) == len(lines) and not first:
        return None
    while kept and not kept[-1].strip():
        kept.pop()
    if first:
        if kept and not TRAILER.match(kept[-1].strip()):
            kept.append(b"")
        kept.append(CLAUDE_TRAILER)
    cleaned = b"\n".join(kept) + b"\n"
    return None if cleaned == message else cleaned


def load_maps() -> dict[bytes, bytes]:
    """Old to new commit ids of every repo rewritten so far, for remapping submodule links."""
    mapping: dict[bytes, bytes] = {}
    for path in MAPS.glob("*.map"):
        for line in path.read_bytes().splitlines():
            old, new = line.split()
            mapping[old] = new
    return mapping


def save_map(name: str, mapping: dict[bytes, bytes]) -> dict[bytes, bytes]:
    """Adds to the repo's map, so a second run, which moves nothing, keeps the first one's ids."""
    path = MAPS / (name + ".map")
    known = dict(line.split() for line in path.read_bytes().splitlines()) if path.exists() else {}
    known = {old: mapping.get(new, new) for old, new in known.items()}
    known.update(mapping)
    path.write_bytes(b"".join(old + b" " + new + b"\n" for old, new in known.items()))
    return known


def git(*args: str, cwd: Path | None = None, capture: bool = True,
        env: dict[str, str] | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=capture,
                          env=None if env is None else {**os.environ, **env})
    if done.returncode != 0:
        print("git %s: %s" % (" ".join(args[:3]), (done.stderr or "").strip()), file=sys.stderr)
        raise subprocess.CalledProcessError(done.returncode, done.args, done.stdout, done.stderr)
    return done.stdout if capture else ""


def remote_git(*args: str, cwd: Path | None = None) -> str:
    """A git command that talks to GitHub, which drops long transfers under load; each is idempotent."""
    for attempt in range(3):
        try:
            return git("-c", "http.version=HTTP/1.1", *args, cwd=cwd)
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(30)
    return ""


class RulesetsLifted:
    """Disables the repo's active rulesets (no force-push on main) for one push, then restores them."""

    def __init__(self, name: str) -> None:
        self.path = "repos/%s/%s/rulesets" % (OWNER, name)
        self.lifted: list[str] = []

    def __enter__(self) -> RulesetsLifted:
        listed = subprocess.run(["gh", "api", self.path, "--jq", '.[] | select(.enforcement == "active") | .id'],
                                capture_output=True, text=True)
        # Private repos on a free plan cannot have rulesets; the API answers 403.
        if listed.returncode != 0 and "Upgrade to GitHub Pro" not in listed.stderr + listed.stdout:
            refuse("cannot list rulesets of %s: %s" % (self.path, listed.stderr.strip()))
        ids = listed.stdout.split() if listed.returncode == 0 else []
        for ruleset in ids:
            subprocess.run(["gh", "api", "-X", "PUT", "%s/%s" % (self.path, ruleset), "-f",
                            "enforcement=disabled"], capture_output=True, check=True)
            self.lifted.append(ruleset)
        return self

    def __exit__(self, *_exc) -> None:
        for ruleset in self.lifted:
            subprocess.run(["gh", "api", "-X", "PUT", "%s/%s" % (self.path, ruleset), "-f",
                            "enforcement=active"], capture_output=True, check=True)


def refs_of(git_dir: Path) -> dict[str, str]:
    listing = git("--git-dir", str(git_dir), "for-each-ref", "--format=%(refname) %(objectname)",
                  "refs/heads", "refs/tags")
    return dict(line.split() for line in listing.splitlines())


def count_credits(mirror: Path) -> int:
    log = git("log", "--all", "--format=<%ae>%n<%ce>%n%(trailers:key=Co-authored-by,valueonly)", cwd=mirror)
    return sum(1 for line in log.splitlines() if line.strip() and is_ai_credit(line.encode()))


def mirror_of(name: str) -> Path:
    mirror = WORK / (name + ".git")
    if mirror.exists():
        shutil.rmtree(mirror)
    WORK.mkdir(parents=True, exist_ok=True)
    remote_git("clone", "--quiet", "--mirror", "https://github.com/%s/%s.git" % (OWNER, name), str(mirror))
    # A detached auto-gc would pack loose objects away while the rewriter writes beside them.
    git("--git-dir", str(mirror), "config", "gc.auto", "0")
    return mirror


class ObjectStore:
    """Raw objects of one repo: read through a cat-file process, written as loose objects."""

    def __init__(self, git_dir: Path) -> None:
        self.git_dir = git_dir
        self.reader = subprocess.Popen(["git", "--git-dir", str(git_dir), "cat-file", "--batch"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def __enter__(self) -> ObjectStore:
        return self

    def __exit__(self, *_exc) -> None:
        self.reader.stdin.close()
        self.reader.wait()

    def read(self, sha: bytes) -> tuple[bytes, bytes]:
        self.reader.stdin.write(sha + b"\n")
        self.reader.stdin.flush()
        header = self.reader.stdout.readline().split()
        if header[1] == b"missing":
            refuse("object %s is missing from %s" % (sha.decode(), self.git_dir))
        body = self.reader.stdout.read(int(header[2]))
        self.reader.stdout.read(1)
        return header[1], body

    def write(self, kind: bytes, body: bytes) -> bytes:
        data = kind + b" " + str(len(body)).encode() + b"\0" + body
        sha = hashlib.sha1(data).hexdigest()
        path = self.git_dir / "objects" / sha[:2] / sha[2:]
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            partial = path.with_suffix(".partial")
            partial.write_bytes(zlib.compress(data))
            partial.rename(path)
        return sha.encode()


IDENTITY = re.compile(rb"^(author|committer) (.*) <([^>]*)> (\S+ \S+)$")
SIGNATURE_HEADERS = (b"gpgsig", b"gpgsig-sha256")


def header_lines(head: bytes) -> list[bytes]:
    """Header fields of a commit, a multi-line field (a signature) kept as one entry."""
    fields: list[bytes] = []
    for line in head.split(b"\n"):
        if line.startswith(b" ") and fields:
            fields[-1] += b"\n" + line
        else:
            fields.append(line)
    return fields


class HistoryRewriter:
    """Rewrites the user's and AI tools' commits; everyone else's stay byte-identical, signed or not."""

    def __init__(self, store: ObjectStore, links: dict[bytes, bytes], link_paths: set[tuple[bytes, ...]],
                 credited: bool, foreign: set[bytes] = frozenset()) -> None:
        self.store = store
        self.foreign = foreign
        self.links = links
        self.link_dirs = {path[:depth] for path in link_paths for depth in range(1, len(path))}
        self.credited = credited
        self.first_done = False
        self.new: dict[bytes, bytes] = {}
        self.trees: dict[tuple[bytes, tuple[bytes, ...]], bytes] = {}

    def tree(self, sha: bytes, prefix: tuple[bytes, ...] = ()) -> bytes:
        if not self.links or (prefix and prefix not in self.link_dirs):
            return sha
        key = (sha, prefix)
        if key not in self.trees:
            self.trees[key] = self.remap_tree(sha, prefix)
        return self.trees[key]

    def remap_tree(self, sha: bytes, prefix: tuple[bytes, ...]) -> bytes:
        _kind, body = self.store.read(sha)
        out = bytearray()
        changed = False
        at = 0
        while at < len(body):
            space = body.index(b" ", at)
            nul = body.index(b"\0", space)
            mode, name = body[at:space], body[space + 1:nul]
            entry = body[nul + 1:nul + 21].hex().encode()
            at = nul + 21
            target = entry
            if mode == b"160000":
                target = self.links.get(entry, entry)
            elif mode == b"40000":
                target = self.tree(entry, prefix + (name,))
            changed = changed or target != entry
            out += mode + b" " + name + b"\0" + bytes.fromhex(target.decode())
        return self.store.write(b"tree", bytes(out)) if changed else sha

    def commit(self, sha: bytes) -> bytes:
        _kind, body = self.store.read(sha)
        head, separator, message = body.partition(b"\n\n")
        fields = header_lines(head)
        author = next(IDENTITY.match(f) for f in fields if f.startswith(b"author "))
        own = sha not in self.foreign and owned(author.group(3), author.group(2))
        parents = [f for f in fields if f.startswith(b"parent ")]
        out = []
        for field in fields:
            key, _, value = field.partition(b" ")
            if key == b"tree":
                field = b"tree " + self.tree(value)
            elif key == b"parent":
                field = b"parent " + self.new.get(value, value)
            elif own and key in (b"author", b"committer"):
                who = IDENTITY.match(field)
                if who and is_ai(who.group(3)):
                    field = key + b" " + USER_NAME + b" <" + USER_EMAIL + b"> " + who.group(4)
            out.append(field)
        if own:
            first = self.credited and not parents and not self.first_done
            self.first_done = self.first_done or first
            message = clean_message(message, first) or message
        if out == fields and message == body.partition(b"\n\n")[2]:
            return sha
        # The object changed, so its signature no longer verifies.
        out = [f for f in out if f.partition(b" ")[0] not in SIGNATURE_HEADERS]
        return self.store.write(b"commit", b"\n".join(out) + separator + message)

    def run(self, commits: list[bytes]) -> None:
        for sha in commits:
            if sha not in self.new:
                self.new[sha] = self.commit(sha)

    def tag(self, sha: bytes) -> bytes:
        """A tag object pointing at the rewritten commit, its now invalid signature dropped."""
        _kind, body = self.store.read(sha)
        head, separator, message = body.partition(b"\n\n")
        fields = header_lines(head)
        target = fields[0].partition(b" ")[2]
        new = self.new.get(target, target)
        if new == target:
            return sha
        fields[0] = b"object " + new
        message = message.split(b"-----BEGIN PGP SIGNATURE-----")[0]
        return self.store.write(b"tag", b"\n".join(fields) + separator + message)


def rev_list(mirror: Path, tips: list[str]) -> list[bytes]:
    if not tips:
        return []
    listing = subprocess.run(["git", "--git-dir", str(mirror), "rev-list", "--topo-order", "--reverse",
                              "--stdin"], input="\n".join(tips) + "\n",
                             capture_output=True, text=True, check=True).stdout
    return [line.encode() for line in listing.split()]


def link_paths(git_dir: Path, revs: list[str]) -> set[tuple[bytes, ...]]:
    """Every path that ever held a submodule link in the history of revs."""
    if not revs:
        return set()
    raw = subprocess.run(["git", "--git-dir", str(git_dir), "log", "--format=", "--raw", "--no-abbrev",
                          "--no-renames", "-m", "--stdin"], input="\n".join(revs).encode() + b"\n",
                         capture_output=True, check=True).stdout
    paths = set()
    for line in raw.splitlines():
        meta, _, path = line.partition(b"\t")
        if b"160000" in meta.split()[:2]:
            paths.add(tuple(path.split(b"/")))
    return paths


def fork_parent(name: str) -> str:
    """The URL of the repo this one forks, or "" for the user's own projects."""
    parent = subprocess.run(["gh", "api", "repos/%s/%s" % (OWNER, name), "--jq", ".parent.full_name // \"\""],
                            capture_output=True, text=True, check=True).stdout.strip()
    return "https://github.com/%s.git" % parent if parent else ""


def upstream_tags(url: str) -> dict[str, tuple[str, str]]:
    """The parent's tags as name to (tag object, peeled commit)."""
    tags: dict[str, tuple[str, str]] = {}
    for line in remote_git("ls-remote", "--tags", url).splitlines():
        sha, ref = line.split("\t")
        tag = ref.removeprefix("refs/tags/").removesuffix("^{}")
        object_, peeled = tags.get(tag, (sha, sha))
        tags[tag] = (object_, sha) if ref.endswith("^{}") else (sha, peeled)
    return tags


def rewrite_history(mirror: Path, name: str, credited: bool) -> dict[bytes, bytes]:
    """Rewrites the mirror's branches and tags; returns old to new ids of every commit that moved.

    A repo an earlier run rewrote wrongly (its map in bad-maps/) is rebuilt from the original
    commits, which GitHub still serves by id; commits pushed on top since then follow along.
    In a fork every commit upstream's branches reach is upstream's, whoever authored it."""
    bad_map = WORK / "bad-maps" / (name + ".map")
    original = {}
    if bad_map.exists():
        original = {new: old for old, new in (line.split() for line in bad_map.read_bytes().splitlines())}
    refs = refs_of(mirror)
    current = rev_list(mirror, list(refs.values()))
    tips = set(refs.values())
    graph = subprocess.run(["git", "--git-dir", str(mirror), "rev-list", "--parents", "--stdin"],
                           input="\n".join(refs.values()) + "\n", capture_output=True, text=True,
                           check=True).stdout
    frontier = {sha.encode() for sha in tips if sha.encode() in original}
    for line in graph.splitlines():
        child, *parents = line.encode().split()
        if child not in original:
            frontier.update(p for p in parents if p in original)
    originals = sorted({original[sha].decode() for sha in frontier})
    if originals:
        remote_git("--git-dir", str(mirror), "fetch", "--quiet", "--no-tags", "origin",
                   *("%s:refs/original/%d" % (sha, i) for i, sha in enumerate(originals)))
    parent = fork_parent(name)
    foreign: set[bytes] = set()
    if parent:
        remote_git("--git-dir", str(mirror), "fetch", "--quiet", "--no-tags", parent, "+refs/heads/*:refs/upstream/*")
        foreign = set(rev_list(mirror, git("--git-dir", str(mirror), "for-each-ref", "--format=%(objectname)",
                                           "refs/upstream").split()))
    with ObjectStore(mirror) as store:
        rewriter = HistoryRewriter(store, load_maps(), link_paths(mirror, ["--all"]), credited, foreign)
        rewriter.run(rev_list(mirror, originals))
        for bad, old in original.items():
            if old in rewriter.new:
                rewriter.new[bad] = rewriter.new[old]
        rewriter.run([sha for sha in current if sha not in original])
        upstream = upstream_tags(parent) if parent and original else {}
        listing = git("--git-dir", str(mirror), "for-each-ref",
                      "--format=%(refname) %(objectname) %(objecttype) %(*objectname)", "refs/heads", "refs/tags")
        moves = []
        from_upstream = []
        for line in listing.splitlines():
            ref, sha, kind, *peeled = line.split()
            if kind == "commit":
                new = rewriter.new[sha.encode()].decode()
            else:
                target = peeled[0].encode() if peeled else sha.encode()
                source = upstream.get(ref.removeprefix("refs/tags/"))
                if source and rewriter.new.get(target, target) == source[1].encode():
                    new = source[0]
                    from_upstream.append(new)
                else:
                    new = rewriter.tag(sha.encode()).decode()
            if new != sha:
                moves.append("update %s %s %s\n" % (ref, new, sha))
    for chunk in range(0, len(from_upstream), 500):
        remote_git("--git-dir", str(mirror), "fetch", "--quiet", "--no-tags", parent,
                   *from_upstream[chunk:chunk + 500])
    subprocess.run(["git", "--git-dir", str(mirror), "update-ref", "--stdin"], input="".join(moves),
                   text=True, check=True)
    for ref in git("--git-dir", str(mirror), "for-each-ref", "--format=%(refname)", "refs/original",
                   "refs/upstream").split():
        git("--git-dir", str(mirror), "update-ref", "-d", ref)
    return {old: new for old, new in rewriter.new.items() if old != new}


def immutable_release_tags(name: str) -> set[str]:
    """Tags of immutable releases, which GitHub never lets move."""
    listing = subprocess.run(["gh", "api", "--paginate", "repos/%s/%s/releases" % (OWNER, name), "--jq",
                              ".[] | select(.immutable) | .tag_name"], capture_output=True, text=True, check=True)
    return {"refs/tags/" + tag for tag in listing.stdout.split()}


def push(mirror: Path, name: str, before: dict[str, str]) -> None:
    """Force-pushes only over what was mirrored, so a push that landed meanwhile is never lost."""
    after = refs_of(mirror)
    locked = immutable_release_tags(name)
    changed = [ref for ref, sha in after.items() if before.get(ref) != sha and ref not in locked]
    for ref in sorted(locked & set(after)):
        if before.get(ref) != after[ref]:
            print("  %s is an immutable release's tag; it keeps the old commit" % ref, flush=True)
    if not changed:
        return
    url = "https://github.com/%s/%s.git" % (OWNER, name)
    leases = ["--force-with-lease=%s:%s" % (ref, before[ref]) for ref in changed if ref in before]
    with RulesetsLifted(name):
        remote_git("push", "--quiet", "--atomic", *leases, url, *("%s:%s" % (ref, ref) for ref in changed),
                   cwd=mirror)


def git_dirs(name: str) -> list[Path]:
    """Every git directory under ~/repo whose origin is the repo: clones and submodule stores."""
    found = []
    candidates = [d for d in (Path.home() / "repo").glob("**/.git") if d.is_dir()
                  and "node_modules" not in d.parts and "build" not in d.parts]
    candidates += [c.parent for d in list(candidates) for c in (d / "modules").glob("**/config")
                   if (d / "modules").is_dir() and (c.parent / "HEAD").is_file()]
    for git_dir in candidates:
        url = subprocess.run(["git", "--git-dir", str(git_dir), "config", "remote.origin.url"],
                             capture_output=True, text=True).stdout.strip()
        if re.search(r"[/:]%s/%s(\.git)?$" % (OWNER, re.escape(name)), url):
            found.append(git_dir)
    return found


def sync_submodules(git_dir: Path, links: dict[bytes, bytes]) -> None:
    """Points each worktree's index and submodule checkout at the rewritten commit of its link."""
    listing = git("--git-dir", str(git_dir), "worktree", "list", "--porcelain")
    for worktree in (line.split(" ", 1)[1] for line in listing.splitlines() if line.startswith("worktree ")):
        staged = git("ls-files", "-s", cwd=Path(worktree))
        for line in staged.splitlines():
            meta, path = line.split("\t", 1)
            mode, sha = meta.split()[:2]
            new = links.get(sha.encode())
            if mode != "160000" or new is None:
                continue
            git("update-index", "--cacheinfo", "160000,%s,%s" % (new.decode(), path), cwd=Path(worktree))
            checkout = Path(worktree) / path
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True,
                                  text=True).stdout.strip()
            if head == sha:
                remote_git("fetch", "--quiet", "origin", cwd=checkout)
                git("checkout", "--quiet", "--detach", new.decode(), cwd=checkout)


def move_git_dir(git_dir: Path, mapping: dict[bytes, bytes]) -> None:
    """Moves branches to their rewritten commits; commits never pushed are rewritten on top."""
    remote_git("--git-dir", str(git_dir), "fetch", "--quiet", "--force", "--tags", "origin")
    heads = {ref: sha for ref, sha in refs_of(git_dir).items() if ref.startswith("refs/heads/")}
    unpushed = subprocess.run(["git", "--git-dir", str(git_dir), "rev-list", "--topo-order", "--reverse",
                               "--stdin"], input="\n".join([*heads.values(), "--not", "--remotes"]) + "\n",
                              capture_output=True, text=True, check=True).stdout.split()
    with ObjectStore(git_dir) as store:
        local = [sha.encode() for sha in unpushed]
        tips = [sha for sha in heads.values() if sha.encode() not in mapping]
        rewriter = HistoryRewriter(store, load_maps(), link_paths(git_dir, tips) if local else set(), False)
        rewriter.new.update(mapping)
        rewriter.run(local)
    moves = "".join("update %s %s %s\n" % (ref, rewriter.new[sha.encode()].decode(), sha)
                    for ref, sha in heads.items() if rewriter.new.get(sha.encode(), sha.encode()) != sha.encode())
    subprocess.run(["git", "--git-dir", str(git_dir), "update-ref", "--stdin"], input=moves, text=True, check=True)
    if "modules" not in git_dir.parts:
        sync_submodules(git_dir, load_maps())


def disclose_one(name: str) -> str:
    checkout = WORK / name
    if checkout.exists():
        shutil.rmtree(checkout)
    remote_git("clone", "--quiet", "--depth", "1", "https://github.com/%s/%s.git" % (OWNER, name), str(checkout))
    readme = next((p for p in checkout.iterdir() if p.name.lower() in ("readme.md", "readme")), None)
    if readme is None:
        readme = checkout / "README.md"
        readme.write_text("# %s\n" % name)
    text = readme.read_text()
    if DISCLOSURE in text:
        shutil.rmtree(checkout)
        return "already disclosed"
    readme.write_text(text.rstrip("\n") + "\n\n" + DISCLOSURE + "\n")
    git("add", readme.name, cwd=checkout)
    git("commit", "--quiet", "-m", "docs(readme): disclose AI assistance", cwd=checkout)
    remote_git("push", "--quiet", "origin", "HEAD", cwd=checkout)
    shutil.rmtree(checkout)
    for clone in (d.parent for d in git_dirs(name) if "modules" not in d.parts):
        remote_git("fetch", "--quiet", "origin", cwd=clone)
        branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone).strip()
        if branch == "HEAD":
            continue
        upstream = "origin/" + branch
        merged = subprocess.run(["git", "merge", "--quiet", "--ff-only", upstream], cwd=clone,
                                capture_output=True, text=True)
        if merged.returncode != 0:
            print("  %s not fast-forwarded: %s" % (clone, merged.stderr.strip().splitlines()[-1]))
    return "disclosed"


def disclose(args: argparse.Namespace) -> int:
    for name in args.names:
        print("%s: %s" % (name, disclose_one(name)))
    return 0


def scan(args: argparse.Namespace) -> int:
    for name in args.names:
        print("%-32s %d AI credits" % (name, count_credits(mirror_of(name))))
    return 0


def rewrite(args: argparse.Namespace) -> int:
    MAPS.mkdir(parents=True, exist_ok=True)
    for name in args.names:
        mirror = mirror_of(name)
        before_refs = refs_of(mirror)
        before = count_credits(mirror)
        mapping = rewrite_history(mirror, name, before > 0)
        after = count_credits(mirror)
        moved = save_map(name, mapping)
        push(mirror, name, before_refs)
        print("%s: %d AI credits -> %d, %d commits rewritten" % (name, before, after,
                                                                  len(mapping)), flush=True)
        for git_dir in git_dirs(name):
            move_git_dir(git_dir, moved)
            print("  moved %s" % git_dir, flush=True)
        if before and args.disclose:
            print("  README: %s" % disclose_one(name), flush=True)
        shutil.rmtree(mirror)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for command, run in (("scan", scan), ("rewrite", rewrite), ("disclose", disclose)):
        sub = commands.add_parser(command)
        sub.add_argument("names", nargs="+")
        sub.set_defaults(run=run)
        if command == "rewrite":
            # A fork's README is upstream's; only the user's own projects get the line.
            sub.add_argument("--no-disclose", dest="disclose", action="store_false")
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
