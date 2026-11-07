#!/usr/bin/env python3
"""Collapse AI credits in a GitHub repo's history to one Claude co-author on its first commit.

  ai_credit.py scan <name>...        count AI credits in each repo, without changing anything
  ai_credit.py rewrite <name>...     rewrite, force-push and disclose each repo, then move clones
                                     (--no-disclose for forks, whose README is upstream's)
  ai_credit.py disclose <name>...    add the AI disclosure line to each repo's README and push

``rewrite`` works on a fresh mirror of ``github.com/<owner>/<name>`` under
``~/repo/scratch/ai-credit/``. In the user's commits and in commits an AI tool authored it removes
every AI ``Co-authored-by`` trailer, makes an AI author or committer the user, and gives the first
commit ``Co-Authored-By: Claude <noreply@anthropic.com>``. Other people's commits (upstream
history in forks and imports) are left alone, so their ids do not change. Submodule links to repos
rewritten earlier are remapped through their saved commit maps, so rewrite dependencies first.

After pushing it moves each local branch of every clone whose ``origin`` is the repo to its
rewritten commit. Only messages change, never trees, so checkouts and uncommitted work are
untouched. A branch with commits that were never pushed is reported, not moved.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
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
    rb"@(anthropic\.com|openai\.com|opencode\.ai)$|^opencode@|@spacebunny$"
    rb"|^copilot@github\.com$|Copilot@users\.noreply\.github\.com$|^685f4c1d-", re.IGNORECASE)
TRAILER = re.compile(rb"^co-authored-by:\s*.*<([^>]*)>\s*$", re.IGNORECASE)
# Copilot's bot authored upstream commits in imported histories; those stay theirs.
FOREIGN_BOT = re.compile(rb"copilot-swe-agent", re.IGNORECASE)


def refuse(message: str) -> None:
    print("ai_credit: " + message, file=sys.stderr)
    sys.exit(2)


def filter_repo_module():
    path = shutil.which("git-filter-repo")
    if path is None:
        refuse("git-filter-repo is not on PATH (uv tool install git-filter-repo)")
    # The script is a uv tool shim; its own interpreter knows where the module lives.
    interpreter = Path(path).read_text().splitlines()[0].removeprefix("#!").strip()
    source = subprocess.run([interpreter, "-c", "import git_filter_repo; print(git_filter_repo.__file__)"],
                            check=True, capture_output=True, text=True).stdout.strip()
    loader = importlib.machinery.SourceFileLoader("git_filter_repo", source)
    spec = importlib.util.spec_from_loader("git_filter_repo", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def is_ai(email: bytes) -> bool:
    return bool(AI_EMAIL.search(email))


def is_ai_trailer(line: bytes) -> bool:
    match = TRAILER.match(line.strip())
    return match is not None and is_ai(match.group(1))


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


def git(*args: str, cwd: Path | None = None, capture: bool = True,
        env: dict[str, str] | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=capture, env=None if env is None else {**os.environ, **env})
    return done.stdout if capture else ""


def refs_of(git_dir: Path) -> dict[str, str]:
    listing = git("--git-dir", str(git_dir), "for-each-ref", "--format=%(refname) %(objectname)",
                  "refs/heads", "refs/tags")
    return dict(line.split() for line in listing.splitlines())


def count_credits(mirror: Path) -> int:
    log = git("log", "--all", "--format=%ae%n%ce%n%(trailers:key=Co-authored-by,valueonly)",
              cwd=mirror)
    return sum(1 for line in log.splitlines() if AI_EMAIL.search(
        (re.search(r"<([^>]*)>", line).group(1) if "<" in line else line.strip()).encode()))


def mirror_of(name: str) -> Path:
    mirror = WORK / (name + ".git")
    if mirror.exists():
        shutil.rmtree(mirror)
    WORK.mkdir(parents=True, exist_ok=True)
    git("clone", "--quiet", "--mirror", "https://github.com/%s/%s.git" % (OWNER, name),
        str(mirror))
    return mirror


def rewrite_history(mirror: Path, credited: bool) -> dict[bytes, bytes]:
    fr = filter_repo_module()
    submodules = load_maps()
    first_done = False

    def on_commit(commit, _metadata) -> None:
        nonlocal first_done
        for change in commit.file_changes:
            if change.mode == b"160000" and change.blob_id in submodules:
                change.blob_id = submodules[change.blob_id]
        if not owned(commit.author_email, commit.author_name):
            return
        if is_ai(commit.author_email):
            commit.author_name, commit.author_email = USER_NAME, USER_EMAIL
        if is_ai(commit.committer_email):
            commit.committer_name, commit.committer_email = USER_NAME, USER_EMAIL
        first = credited and not commit.parents and not first_done
        first_done = first_done or first
        cleaned = clean_message(commit.message, first)
        if cleaned is not None:
            commit.message = cleaned

    args = fr.FilteringOptions.parse_args(["--force", "--quiet", "--source", str(mirror),
                                           "--target", str(mirror)])
    fr.RepoFilter(args, commit_callback=on_commit).run()
    mapping: dict[bytes, bytes] = {}
    for line in (mirror / "filter-repo" / "commit-map").read_bytes().splitlines()[1:]:
        old, new = line.split()
        if old != new:
            mapping[old] = new
    return mapping


def push(mirror: Path, name: str, before: dict[str, str]) -> None:
    """Force-pushes only over what was mirrored, so a push that landed meanwhile is never lost."""
    after = refs_of(mirror)
    changed = [ref for ref, sha in after.items() if before.get(ref) != sha]
    if not changed:
        return
    url = "https://github.com/%s/%s.git" % (OWNER, name)
    leases = ["--force-with-lease=%s:%s" % (ref, before[ref]) for ref in changed if ref in before]
    git("push", "--quiet", *leases, url, *("%s:%s" % (ref, ref) for ref in changed),
        cwd=mirror, capture=False)


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


def on_remote(git_dir: Path, sha: str) -> bool:
    return git("--git-dir", str(git_dir), "for-each-ref", "--contains", sha, "refs/remotes").strip() != ""


def replay(git_dir: Path, tip: str, mapping: dict[bytes, bytes]) -> str | None:
    """Recreates commits never pushed on the rewritten base, tree for tree; None if not linear."""
    chain = []
    sha = tip
    while sha.encode() not in mapping and not on_remote(git_dir, sha):
        parents = git("--git-dir", str(git_dir), "rev-list", "--parents", "-n1", sha).split()[1:]
        if len(parents) != 1:
            return None
        chain.append(sha)
        sha = parents[0]
    base = mapping.get(sha.encode(), sha.encode()).decode()
    for old in reversed(chain):
        fields = git("--git-dir", str(git_dir), "log", "-1",
                     "--format=%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd%x00%T", "--date=raw",
                     old).rstrip("\n").split("\0")
        message = git("--git-dir", str(git_dir), "log", "-1", "--format=%B", old).encode()
        env = dict(zip(("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"), fields[:6]))
        for role in ("AUTHOR", "COMMITTER"):
            if is_ai(env["GIT_%s_EMAIL" % role].encode()):
                env["GIT_%s_NAME" % role] = USER_NAME.decode()
                env["GIT_%s_EMAIL" % role] = USER_EMAIL.decode()
        done = subprocess.run(["git", "--git-dir", str(git_dir), "commit-tree", fields[6], "-p", base],
                              input=clean_message(message, False) or message, capture_output=True, check=True,
                              env={**os.environ, **env})
        base = done.stdout.decode().strip()
    return base


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
                subprocess.run(["git", "fetch", "--quiet", "origin"], cwd=checkout)
                git("checkout", "--quiet", "--detach", new.decode(), cwd=checkout)


def move_git_dir(git_dir: Path, mapping: dict[bytes, bytes]) -> list[str]:
    """Moves branches and tags to their rewritten commits; returns branches it could not move."""
    git("--git-dir", str(git_dir), "fetch", "--quiet", "--force", "--tags", "origin")
    stuck = []
    for ref, sha in refs_of(git_dir).items():
        new = mapping.get(sha.encode())
        if new is None and ref.startswith("refs/heads/") and not on_remote(git_dir, sha):
            replayed = replay(git_dir, sha, mapping)
            if replayed is None:
                stuck.append(ref)
                continue
            new = replayed.encode()
        if new is not None:
            git("--git-dir", str(git_dir), "update-ref", ref, new.decode(), sha)
    if "modules" not in git_dir.parts:
        sync_submodules(git_dir, load_maps())
    return stuck


def disclose_one(name: str) -> str:
    checkout = WORK / name
    if checkout.exists():
        shutil.rmtree(checkout)
    git("clone", "--quiet", "--depth", "1", "https://github.com/%s/%s.git" % (OWNER, name),
        str(checkout))
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
    git("push", "--quiet", "origin", "HEAD", cwd=checkout, capture=False)
    shutil.rmtree(checkout)
    for clone in (d.parent for d in git_dirs(name) if "modules" not in d.parts):
        git("fetch", "--quiet", "origin", cwd=clone)
        branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone).strip()
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
    status = 0
    for name in args.names:
        mirror = mirror_of(name)
        before_refs = refs_of(mirror)
        before = count_credits(mirror)
        mapping = rewrite_history(mirror, before > 0)
        after = count_credits(mirror)
        (MAPS / (name + ".map")).write_bytes(b"".join(o + b" " + n + b"\n"
                                                      for o, n in mapping.items()))
        push(mirror, name, before_refs)
        print("%s: %d AI credits -> %d, %d commits rewritten" % (name, before, after,
                                                                  len(mapping)), flush=True)
        for git_dir in git_dirs(name):
            stuck = move_git_dir(git_dir, mapping)
            print("  moved %s%s" % (git_dir, "; not linear, not moved: " + " ".join(stuck)
                                     if stuck else ""), flush=True)
            status = status or (1 if stuck else 0)
        if before and args.disclose:
            print("  README: %s" % disclose_one(name), flush=True)
        shutil.rmtree(mirror)
    return status


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
