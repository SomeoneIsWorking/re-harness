#!/usr/bin/env python3
"""Prove each harness tool can give BOTH answers, on a corpus built here.

These tools are how this stack decides what has been proven and what has
already been tried. A tool of that kind failing silently -- answering "no
claims match" from a directory it never read, "no issues found" because the
corpus was empty -- is worse than no tool: the answer looks the same as a real
negative, and the whole point is to stop work being re-derived.

So each check below runs the tool twice: once over a corpus that MUST produce a
hit, and once over an empty one that MUST NOT, and fails if either answer is
wrong. `re_frontier` has its own, better selftest (it performs a real edit and
verifies every non-blank line survived); this defers to it rather than
duplicating it.

    python3 tests/run.py
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run(args, cwd):
    p = subprocess.run([sys.executable] + args, cwd=cwd,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def check(name, ok, detail=""):
    print("  %-46s %s" % (name, "ok" if ok else "FAIL"))
    if not ok and detail:
        print("      " + detail.strip().replace("\n", "\n      ")[:600])
    return 0 if ok else 1


def claims_corpus(root, body):
    d = os.path.join(root, "docs", "info", "claims")
    os.makedirs(d)
    with open(os.path.join(d, "001-a-claim.md"), "w") as f:
        f.write("---\nid: C001\nkind: claim\nstatus: holds\ntags: widget\n---\n"
                "\n## Claim\n\n%s\n" % body)


def issues_corpus(root, title):
    d = os.path.join(root, "docs", "issues")
    os.makedirs(d)
    with open(os.path.join(d, "0001-a-bug.md"), "w") as f:
        f.write("---\nid: 1\ntitle: %s\nstatus: open\n"
                "symptom: the widget emits a spurious frobnicator\n"
                "tags: widget\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"
                % title)


def main():
    fails = 0
    print("re-harness selftest")

    # --- re_frontier: defer to its own, stronger selftest -------------------
    rc, out = run([os.path.join(ROOT, "re_frontier.py"), "selftest"], ROOT)
    fails += check("re_frontier: its own edit-preservation selftest",
                   rc == 0 and "selftest OK" in out, out)

    # --- info.py: must FIND a claim, and must not invent one ---------------
    with tempfile.TemporaryDirectory() as d:
        claims_corpus(d, "the widget is proven to frobnicate")
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "frobnicate"], d)
        fails += check("info.py: finds a claim that is there",
                       rc == 0 and "C001" in out, out)

    with tempfile.TemporaryDirectory() as d:
        claims_corpus(d, "the widget is proven to frobnicate")
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "zzzznotaword"], d)
        fails += check("info.py: reports NO match for a word not present",
                       rc == 0 and "C001" not in out, out)

    # An empty tree must not read as "nothing has ever been proven" without
    # saying so -- that is the negative this tool must never fake.
    with tempfile.TemporaryDirectory() as d:
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "frobnicate"], d)
        fails += check("info.py: no corpus does not produce a false hit",
                       "C001" not in out, out)

    # --- catalog.py: must FIND an issue, and must not invent one -----------
    with tempfile.TemporaryDirectory() as d:
        issues_corpus(d, "Widget emits a spurious frobnicator")
        rc, out = run([os.path.join(ROOT, "catalog.py"), "search", "frobnicator"], d)
        fails += check("catalog.py: finds an issue that is there",
                       rc == 0 and "#1" in out, out)

    with tempfile.TemporaryDirectory() as d:
        issues_corpus(d, "Widget emits a spurious frobnicator")
        rc, out = run([os.path.join(ROOT, "catalog.py"), "search", "zzzznotaword"], d)
        fails += check("catalog.py: reports NO match for an absent symptom",
                       "#1" not in out, out)

    with tempfile.TemporaryDirectory() as d:
        rc, out = run([os.path.join(ROOT, "catalog.py"), "search", "frobnicator"], d)
        fails += check("catalog.py: no corpus does not produce a false hit",
                       "#1" not in out, out)

    print("re-harness selftest: %s (%d check(s) failed)"
          % ("FAILED" if fails else "PASSED", fails))
    return fails


if __name__ == "__main__":
    sys.exit(main())
