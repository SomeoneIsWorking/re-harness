---
name: go-public
description: Audit a git repo's FULL HISTORY for anything that must not ship publicly before flipping it to public — copyrighted assets (ROMs/disc images), machine-specific home paths and usernames, and committed docs that reference PRIVATE gitignored content. Ships a zero-dependency CLI (go_public.py) that scans, reports with commit provenance, and generates a git-filter-repo replace-text rules file (never rewrites on its own). Use when asked to "make this repo public", "go public", "publish this repo", "check the history is clean", "scrub personal paths from history", or before pushing a private repo to a public remote.
---

# go-public — pre-publication history cleanliness gate

Flipping a private repo to public exposes its **entire git history**, not just
the current tree. A clean working tree means nothing if commit #40 baked in a ROM
or an absolute path into the maintainer's home directory. This skill audits the full history against three
criteria and reports every hit with provenance, so you fix the root (rewrite the
offending blobs) rather than papering the tip.

The scanner detects and reports; it never rewrites history. If history contains a
copyrighted blob or machine-specific path, fix the tip and use `git filter-repo`
to scrub the offending content while preserving commits and messages. Squashing
to an orphan commit discards history and is a last resort. The `rules` command
generates a replace-text starting point that must be reviewed before use.

Rewriting and force-pushing history require the user's go-ahead under the
canonical global instructions. The audit and a concrete remediation plan can be
prepared before that decision. After authorization, verify the published state.

## The three checks

- **A. copyright** — disc images / ROMs (`*.rvz *.iso *.gcm *.wbfs …`) and any
  oversized binary blob (`> --max-bytes`, default 2 MB) that ever existed in
  history. These are hard blockers.
- **B. paths** — any path outside the repo dir baked into blob **text**, ALL
  blocking: absolute Unix, macOS, root-account, tilde-expanded, mounted-drive,
  and Windows paths, plus configured usernames. A shell-shortened user-data path
  is **not** an acceptable "portable" form—it still references the reader's home
  and must become repo-relative, an environment variable, or a documented
  in-code default, not a baked literal. (A `review` severity exists in the tool
  only as a deliberate per-repo opt-in downgrade; nothing uses it by default.)
- **C. gitignore** — a committed doc that references gitignored **private data**.
  Two benign classes are deliberately NOT flagged, because referencing them is
  correct and expected:
  - **regenerable output** — `build/`, `generated/`, `scratch/`, `*.o`, logs …
  - **supply-your-own input** — `.env` (your config), disc images / ROM (yours).

  Only ignored patterns that are *neither* (i.e. private data a reader can't get
  and isn't told to provide) are flagged. A well-formed repo whose `.gitignore`
  is all output+input reads clean here; add `private_notes/` to the ignore and
  reference it from a committed doc and C surfaces it.

## Usage

Run from the repo root:

```
go_public.py scan                 # all three checks over FULL history -> report
go_public.py scan --current       # working tree + HEAD only (fast pre-commit gate)
go_public.py copyright            # just check A
go_public.py paths                # just check B
go_public.py gitignore            # just check C
go_public.py scan --json          # machine-readable
go_public.py rules -o replace.txt # generate a filter-repo replace-text file (see below)
go_public.py -C /path/to/repo scan
```

Exit status: `0` = no blocking findings, `1` = blocking findings (copyright or
critical paths), `2` = usage/environment error. Review-only and gitignore hits
are printed but do not by themselves set a nonzero exit — they need eyes, not a
gate.

The full-history scan reads every text blob once (deduped); on a ~1.7k-commit /
~11k-object repo it runs in well under a minute. Use `--current` for a fast
loop while fixing, then a final full `scan` before publishing.

## Remediation flow

1. **Fix the tip first.** Edit the live files so the current tree is clean
   (repo-relative paths, `<HOME>`/env vars, drop out-of-repo references).
   Re-run `go_public.py scan --current` until it's clean. Commit.
2. **After the user's go-ahead, purge copyrighted blobs from history** (check A hits):
   ```
   git filter-repo --path <that/file> --invert-paths
   ```
   (or `--path-glob '*.iso'`). Run in a fresh mirror clone; filter-repo refuses a
   repo with a remote by default — that's a guardrail, not an error to force past.
3. **Scrub machine-specific strings from history** (check B criticals):
   ```
   go_public.py rules -o replace.txt      # generates a starter mapping
   $EDITOR replace.txt                     # REVIEW every right-hand side
   git filter-repo --replace-text replace.txt
   ```
   `rules` emits `literal==>replacement` lines (longest paths first so specific
   paths win over prefixes), with heuristic defaults (`.../repo/<name>` → `.`,
   `.../.Codex/...` → `<local-notes>`, other home paths → `<HOME>`, usernames →
   `user`). **The defaults are a starting point — confirm each before running.**
4. **Re-scan the rewritten history** in the isolated rewrite clone with
   `go_public.py scan`. Iterate until clean.
5. **Push the clean history** after the user's go-ahead. Rewriting changes every
   downstream hash; existing clones diverge.
6. **Delete stale remote branches.** A force-push only replaces the pushed branch;
   OTHER remote branches (old `worktree-*`, backups, `master`) still expose the full
   pre-scrub history publicly. `git ls-remote` the origin and
   `git push origin --delete <branch>` every ref that isn't the clean one.
7. **FLIP THE VISIBILITY — this is the step people forget.** Scrubbing content and
   force-pushing does NOT make a repo public; "public" is a GitHub *setting*. A repo
   whose history is clean but whose visibility is still Private is not published.
   ```
   gh repo view  <owner>/<repo> --json visibility -q .visibility        # PRIVATE?
   gh repo edit  <owner>/<repo> --visibility public --accept-visibility-change-consequences
   ```
   Do this for EVERY repo asked about AND every nested submodule they depend on
   (a private submodule breaks `git clone --recursive`). Verify each reads PUBLIC.
   Clone the published branch alone and run `go_public.py scan` on that clone;
   local refs may still expose old blobs that are no longer published.

With a submodule, publish the dependency first and repoint the parent's gitlink
(`git update-index --cacheinfo 160000,<new-sha>,<path>`) before pushing the parent,
else it references a commit that no longer exists.

## Configuration

`GO_PUBLIC_NAMES=a,b` adds account names to the scan without changing tracked
source. Other scanner policy is shared in the canonical `tools/go_public.py`;
extend and test that implementation for a missing generally applicable pattern.
Consuming projects invoke the shared tool through their resolver rather than
copying it.
