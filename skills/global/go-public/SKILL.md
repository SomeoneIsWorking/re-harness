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

It DETECTS and REPORTS; it never rewrites history on its own. But **history
rewriting is the NORMAL, expected remediation here** — not a scary last resort.
When history carries an outside-repo path or a copyrighted blob, the fix is to
rewrite those blobs out of history with `git filter-repo` and force-push. The
tool's `rules` command generates a replace-text file to drive that rewrite.

> **Standing directive — SCRUB history, don't wipe it (USER, corrected 2026-07-23).**
> An earlier version of this note said the user "does not care about preserving git
> history" and that hashes are "disposable". That was an OVERSTATEMENT and it caused
> real damage: it was read as a licence to squash-and-force-push on every publish,
> which repeatedly destroyed the public history and every commit message. What the
> user actually authorised was a ONE-TIME history wipe to GO public — i.e. the
> history from BEFORE going public is what didn't matter. It has already happened.
>
> The real rule: **history is worth keeping, and a wipe is a last resort** — it is
> on the table only when scrubbing the history cleanly would be *insurmountable*.
> Rewriting hashes with `filter-repo` is NOT a wipe: it keeps every commit and
> message, and is the normal remediation. Squashing to one orphan commit IS a wipe.
> Prefer, in order: (1) fix the tip; (2) `filter-repo` the offending blobs/strings
> out of history, preserving commits; (3) only if that is genuinely intractable,
> propose a wipe — and say why it is intractable.
>
> Force-pushing is fine and expected (rewriting changes hashes). Do NOT ask for
> go-ahead before a scrub, and do not leave a leak in to avoid one. Just don't
> collapse the commits.
>
> **The agent runs the force-push ITSELF** (USER 2026-07-17). There is no
> classifier block on publishing; do not hand the final push back to the user or
> stop at "here's a script for you to run." Do the rewrite AND the
> `git push --force`, then re-scan the published state to green.

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

## Remediation flow (user go-ahead required — this rewrites history)

1. **Fix the tip first.** Edit the live files so the current tree is clean
   (repo-relative paths, `<HOME>`/env vars, drop out-of-repo references).
   Re-run `go_public.py scan --current` until it's clean. Commit.
2. **Purge copyrighted blobs from history** (check A hits):
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
4. **Re-scan the rewritten history**: `go_public.py scan`. Iterate until clean.
   Re-scan the ACTUAL published state, not a local orphan branch — a local clone
   keeps the old `main` ref so its `--all` scan still shows scrubbed blobs; clone
   the pushed branch alone (`git clone --branch <b> --single-branch` or `--depth 1`
   from the remote) and scan THAT.
5. **Push the clean history**: force-push (the agent does this itself — no classifier
   block, see the standing directive above). Rewriting changes every downstream hash;
   existing clones diverge.
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

**Squash-to-orphan — LAST RESORT, not a shortcut (corrected 2026-07-23).** Publishing
each repo as a single orphan commit (`git checkout --orphan clean && git add -A &&
git commit`, force-push `clean:main`) does drop every leaky blob and oversized `.o`
at once — but it DESTROYS every commit and message, and re-running it per publish
destroys the public history each time. Use it only when scrubbing history cleanly is
genuinely insurmountable, and say why. Normal remediation is `filter-repo`, which
preserves the commits. With a submodule, whichever route you take, publish the
dependency FIRST and repoint the parent's gitlink
(`git update-index --cacheinfo 160000,<new-sha>,<path>`) before pushing the parent,
else it references a commit that no longer exists.

## Tuning per repo

`go_public.py` is stdlib-only and config-driven — edit the CONFIG block at the top:

- `COPYRIGHT_PATTERNS` — asset/disc-image extensions to treat as copyrighted.
- `USERNAME` / `USERNAME_ALT` / `FOREIGN_PATH_PATTERNS` — the account names and
  path shapes to hunt, and their severity (critical vs review).
- `BENIGN_IGNORE` — the regenerable-output + supply-your-own-input gitignore
  patterns that check C must NOT flag. Anything in `.gitignore` not matched here
  is treated as private-data-by-default (fail closed) and its references get
  flagged. When a repo legitimately ignores new build/input classes, add them
  here so C stays quiet; when it ignores genuine private data, leave it out so C
  catches stray references.
- `TEXT_EXTS` — which extensions count as text for the content scans.

For a repo you'll hand to collaborators who lack this skill, copy `go_public.py`
into the project's `tools/` and commit it, so the pre-publication check travels
with the code.
