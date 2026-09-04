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
import re
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
SCRATCH = os.path.join(ROOT, "scratch", "tests")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, TOOLS)
import source_boundary  # noqa: E402


def tempdir():
    return tempfile.TemporaryDirectory(dir=SCRATCH)


def run(args, cwd, env=None):
    child_env = dict(os.environ if env is None else env)
    # The tools intentionally print Unicode status markers.  Windows otherwise
    # chooses a legacy code page for redirected subprocess streams, which makes
    # the same shipping CLI fail as soon as a marker cannot be represented.
    child_env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable] + args, cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", env=child_env)
    return p.returncode, p.stdout + p.stderr


def check(name, ok, detail=""):
    print("  %-46s %s" % (name, "ok" if ok else "FAIL"))
    if not ok and detail:
        print("      " + detail.strip().replace("\n", "\n      ")[:600])
    return 0 if ok else 1


def claims_corpus(root, body):
    d = os.path.join(root, "docs", "info", "claims")
    os.makedirs(d)
    with open(os.path.join(d, "001-a-claim.md"), "w", encoding="utf-8") as f:
        f.write("---\nid: C001\nkind: claim\nstatus: holds\ntags: widget\n---\n"
                "\n## Claim\n\n%s\n" % body)


def issues_corpus(root, title):
    d = os.path.join(root, "docs", "issues")
    os.makedirs(d)
    with open(os.path.join(d, "0001-a-bug.md"), "w", encoding="utf-8") as f:
        f.write("---\nid: 1\ntitle: %s\nstatus: open\nstate_items: S001\n"
                "symptom: the widget emits a spurious frobnicator\n"
                "tags: widget\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"
                % title)


def state_corpus(root, state="verified", state_id="S001"):
    docs = os.path.join(root, "docs")
    os.makedirs(os.path.join(docs, "issues"), exist_ok=True)
    with open(os.path.join(docs, "project-goals.md"), "w", encoding="utf-8") as f:
        f.write("# Goals\n\n## G001 — Frobnication\n")
    with open(os.path.join(docs, "project-state.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# Project state\n\n## Current focus\n\n**{state_id} — frobstate**\n\n"
            "## Capability inventory\n\n"
            "| ID | Capability or outcome | State | Factual dependency | Goals |\n"
            "|---|---|---|---|---|\n"
            f"| {state_id} | frobstate capability | {state} | — | G001 |\n\n"
            f"## State details and evidence\n\n### {state_id} — frobstate: {state}\n\n"
            "Evidence: observed a positive and negative frobnication.\n"
        )
    with open(
        os.path.join(docs, "issues", "0001-frob.md"), "w", encoding="utf-8"
    ) as f:
        f.write(
            f"---\nid: 1\ntitle: Frob\nstatus: open\nstate_items: {state_id}\n---\n"
        )


def main():
    fails = 0
    print("shared-skills selftest")

    oversized = []
    for name in sorted(os.listdir(TOOLS)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(TOOLS, name)
        with open(path, encoding="utf-8") as source:
            lines = sum(1 for _ in source)
        if lines > 1200:
            oversized.append(f"{path}: {lines} lines (limit 1200)")
    fails += check(
        "structure: first-party Python tools stay bounded",
        not oversized,
        "\n".join(oversized),
    )

    source_policy = {
        "source_suffixes": [".cpp"],
        "source_names": ["CMakeLists.txt"],
        "excluded_roots": ["docs", "external"],
        "excluded_paths": [],
        "forbidden_tokens": ["retired_call"],
        "forbidden_include_fragments": ["retired/runtime/"],
        "forbidden_path_components": ["generated"],
        "allowed_shell_paths": ["run.sh"],
    }
    clean_source = PurePosixPath("game/clean.cpp")
    excluded_source = PurePosixPath("docs/historical.cpp")
    source_fixtures = {
        clean_source: '#include "native_dispatch.h"\n',
        excluded_source: "retired_call",
    }
    clean_result = source_boundary.inspect_tree(
        source_fixtures, source_fixtures, source_policy
    )
    fails += check(
        "source_boundary: accepts live clean and excluded evidence",
        not clean_result,
        "\n".join(clean_result),
    )
    bad_fixtures = {
        PurePosixPath("game/bad.cpp"): (
            'retired_call();\n#include "retired/runtime/core.h"\n'
        ),
        PurePosixPath("generated/body.cpp"): "",
        PurePosixPath("tools/legacy.sh"): "#!/bin/sh\n",
    }
    bad_result = source_boundary.inspect_tree(bad_fixtures, bad_fixtures, source_policy)
    fails += check(
        "source_boundary: reports every configured negative",
        len(bad_result) == 4,
        "\n".join(bad_result),
    )

    # --- cleanup-files: validate the whole explicit set before unlinking -----
    cleanup = os.path.join(TOOLS, "cleanup-files")
    with tempdir() as d:
        victim = os.path.join(d, "victim.txt")
        with open(victim, "w", encoding="utf-8") as target:
            target.write("remove me\n")
        rc, out = run([cleanup, "victim.txt"], d)
        fails += check(
            "cleanup-files: removes an explicit in-tree file",
            rc == 0 and not os.path.exists(victim) and "removed victim.txt" in out,
            out,
        )

    with tempdir() as d:
        victim = os.path.join(d, "victim.txt")
        os.mkdir(os.path.join(d, "directory"))
        with open(victim, "w", encoding="utf-8") as target:
            target.write("must survive\n")
        rc, out = run([cleanup, "victim.txt", "directory"], d)
        fails += check(
            "cleanup-files: refuses partial cleanup on an invalid target",
            rc == 2 and os.path.exists(victim) and "directory" in out,
            out,
        )

    with tempdir() as d:
        work = os.path.join(d, "work")
        os.mkdir(work)
        outside = os.path.join(d, "outside.txt")
        with open(outside, "w", encoding="utf-8") as target:
            target.write("must survive\n")
        rc, out = run([cleanup, "../outside.txt"], work)
        fails += check(
            "cleanup-files: refuses a target outside the working tree",
            rc == 2 and os.path.exists(outside) and "outside" in out,
            out,
        )

    # --- compatibility names: old and canonical paths are one implementation
    for name in ("catalog.py", "info.py", "project_state.py", "re_frontier.py"):
        root_entry = os.path.join(ROOT, name)
        canonical = os.path.join(TOOLS, name)
        fails += check(
            f"compatibility: {name} resolves to tools/",
            os.path.realpath(root_entry) == os.path.realpath(canonical),
            f"{root_entry} -> {os.path.realpath(root_entry)}; expected {canonical}",
        )

    # --- re_frontier: defer to its own, stronger selftest -------------------
    rc, out = run([os.path.join(ROOT, "re_frontier.py"), "selftest"], ROOT)
    fails += check("re_frontier: its own edit-preservation selftest",
                   rc == 0 and "selftest OK" in out, out)

    rc, out = run([os.path.join(ROOT, "info.py"), "claim", "check", "--selftest"], ROOT)
    fails += check(
        "info.py: its own symbol/history selftest",
        rc == 0 and "shallow history" in out and "selftest PASSED" in out,
        out,
    )

    # --- info.py: must FIND a claim, and must not invent one ---------------
    with tempdir() as d:
        claims_corpus(d, "the widget is proven to frobnicate")
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "frobnicate"], d)
        fails += check("info.py: finds a claim that is there",
                       rc == 0 and "C001" in out, out)

    with tempdir() as d:
        claims_corpus(d, "the widget is proven to frobnicate")
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "zzzznotaword"], d)
        fails += check("info.py: reports NO match for a word not present",
                       rc == 0 and "C001" not in out, out)

    # Rewriting empty frontmatter values must not add a trailing separator
    # space. This is the normal shape of a claim created without tags, and a
    # confirmation must remain clean under a repository whitespace gate.
    with tempdir() as d:
        claims_corpus(d, "the widget is proven to frobnicate")
        claim = os.path.join(d, "docs", "info", "claims", "001-a-claim.md")
        with open(claim, encoding="utf-8") as source:
            text = source.read().replace("tags: widget\n", "tags:\n")
        with open(claim, "w", encoding="utf-8") as target:
            target.write(text)
        rc, out = run([os.path.join(ROOT, "info.py"), "claim", "confirm", "C001",
                       "--evidence", "the negative control was repeated"], d)
        with open(claim, encoding="utf-8") as source:
            confirmed = source.read()
        trailing = [line for line in confirmed.splitlines() if line.endswith((" ", "\t"))]
        fails += check("info.py: empty frontmatter stays whitespace-clean",
                       rc == 0 and "tags:\n" in confirmed and not trailing, out)

    timestamp_probe = (
        "import sys; "
        f"sys.path.insert(0, {TOOLS!r}); "
        "from info_time import now_stamp, timestamp_epoch; "
        "print(now_stamp()); print(timestamp_epoch('2026-08-30 03:15:45'))"
    )
    epochs = []
    stamps = []
    for zone in ("UTC0", "IST-3"):
        rc, out = run(["-c", timestamp_probe], ROOT, {**os.environ, "TZ": zone})
        lines = out.splitlines()
        if rc == 0 and len(lines) == 2:
            stamps.append(lines[0])
            epochs.append(lines[1])
    fails += check(
        "info.py: claim timestamps are timezone-portable",
        len(set(epochs)) == 1 and len(epochs) == 2
        and all(re.search(r"[+-]\d\d:\d\d$", stamp) for stamp in stamps),
        f"stamps={stamps!r}; epochs={epochs!r}",
    )

    # An empty tree must not read as "nothing has ever been proven" without
    # saying so -- that is the negative this tool must never fake.
    with tempdir() as d:
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "frobnicate"], d)
        fails += check("info.py: no corpus does not produce a false hit",
                       "C001" not in out, out)

    # --- catalog.py: must FIND an issue, and must not invent one -----------
    # Direct file search must include a newly-created, untracked state document.
    with tempdir() as d:
        state_corpus(d)
        rc, out = run([os.path.join(ROOT, "info.py"), "brief", "frobstate"], d)
        fails += check("info.py: finds untracked project state",
                       rc == 0 and "PROJECT STATE" in out and "S001" in out, out)

    # --- project state: valid links pass and an invalid state fails ----------
    with tempdir() as d:
        state_corpus(d)
        rc, out = run([os.path.join(ROOT, "project_state.py"), "--root", d], ROOT)
        fails += check("project_state.py: accepts a coherent state graph",
                       rc == 0 and "0 problem(s)" in out, out)

    with tempdir() as d:
        state_corpus(d, state_id="S5b")
        rc, out = run([os.path.join(ROOT, "project_state.py"), "--root", d], ROOT)
        fails += check("project_state.py: accepts a stable suffix ID",
                       rc == 0 and "0 problem(s)" in out, out)

    with tempdir() as d:
        state_corpus(d, state="done")
        rc, out = run([os.path.join(ROOT, "project_state.py"), "--root", d], ROOT)
        fails += check("project_state.py: rejects an invalid state",
                       rc == 1 and "invalid state 'done'" in out, out)

    with tempdir() as d:
        issues_corpus(d, "Widget emits a spurious frobnicator")
        rc, out = run([os.path.join(ROOT, "catalog.py"), "search", "frobnicator"], d)
        fails += check("catalog.py: finds an issue that is there",
                       rc == 0 and "#1" in out, out)

    with tempdir() as d:
        issues_corpus(d, "Widget emits a spurious frobnicator")
        rc, out = run([os.path.join(ROOT, "catalog.py"), "search", "zzzznotaword"], d)
        fails += check("catalog.py: reports NO match for an absent symptom",
                       "#1" not in out, out)

    with tempdir() as d:
        rc, out = run([os.path.join(ROOT, "catalog.py"), "search", "frobnicator"], d)
        fails += check("catalog.py: no corpus does not produce a false hit",
                       "#1" not in out, out)

    with tempdir() as d:
        rc, out = run([os.path.join(ROOT, "catalog.py"), "list"], d)
        fails += check(
            "catalog.py: missing corpus is not an empty catalog",
            rc != 0 and "searched NOTHING" in out,
            out,
        )

    with tempdir() as d:
        issues_corpus(d, "Widget emits a spurious frobnicator")
        rc, out = run([os.path.join(ROOT, "catalog.py"), "list", "--state-item", "S001"], d)
        fails += check("catalog.py: filters by project-state link",
                       rc == 0 and "#1" in out and "<S001>" in out, out)

    with tempdir() as d:
        os.makedirs(os.path.join(d, "docs", "issues"))
        catalog = os.path.join(ROOT, "catalog.py")
        rc, out = run(
            [catalog, "add", "Tagged issue", "--tag", "reported", "--tag", "rendering"],
            d,
        )
        first_rc, first_out = run([catalog, "list", "--tag", "reported"], d)
        second_rc, second_out = run([catalog, "list", "--tag", "rendering"], d)
        fails += check(
            "catalog.py: repeated tags accumulate",
            rc == 0 and first_rc == 0 and second_rc == 0
            and "#1" in first_out and "#1" in second_out,
            out + first_out + second_out,
        )

    # --- installer: all supported homes converge, and tampering is detected --
    with tempdir() as d:
        system_dir = os.path.join(d, ".codex", "skills", ".system")
        os.makedirs(system_dir)
        marker = os.path.join(system_dir, "owned-by-codex")
        with open(marker, "w", encoding="utf-8") as f:
            f.write("preserve me\n")
        installer = os.path.join(TOOLS, "install_skills.py")
        rc, out = run([installer, "--home", d, "install"], ROOT)
        expected = 17 * 3
        links = []
        for agent in (".agents", ".codex", ".claude"):
            root = os.path.join(d, agent, "skills")
            links.extend(
                os.path.join(root, name)
                for name in os.listdir(root)
                if os.path.islink(os.path.join(root, name))
            )
        relative = all(not os.path.isabs(os.readlink(path)) for path in links)
        fails += check(
            "installer: creates every relative skill discovery link",
            rc == 0 and len(links) == expected and relative,
            out + f"\nlinks={len(links)}, expected={expected}, relative={relative}",
        )
        instruction_links = (
            os.path.join(d, ".agents", "AGENTS.md"),
            os.path.join(d, ".codex", "AGENTS.md"),
            os.path.join(d, ".claude", "CLAUDE.md"),
            os.path.join(d, "repo", "AGENTS.md"),
        )
        tool_links = tuple(
            os.path.join(d, agent, "bin", name)
            for agent in (".agents", ".codex", ".claude")
            for name in (
                "catalog.py", "cleanup-files", "codemap.py", "go_public.py",
                "info.py", "project_state.py", "re_frontier.py", "safekill",
            )
        )
        shared_links = instruction_links + tool_links
        fails += check(
            "installer: links every global instruction and tool",
            all(os.path.islink(path) for path in shared_links)
            and all(not os.path.isabs(os.readlink(path)) for path in shared_links),
            out,
        )
        fails += check(
            "installer: preserves vendor-owned system skills",
            os.path.isfile(marker),
            out,
        )
        rc, out = run([installer, "--home", d, "check"], ROOT)
        fails += check("installer: verifies an intact installation", rc == 0, out)

        stale = os.path.join(d, ".agents", "skills", "retired-skill")
        stale_source = os.path.join(ROOT, "skills", "retired", "retired-skill")
        os.symlink(os.path.relpath(stale_source, os.path.dirname(stale)), stale)
        rc, out = run([installer, "--home", d, "check"], ROOT)
        fails += check(
            "installer: detects a retired canonical skill link",
            rc == 1 and "retired-skill: stale canonical skill link" in out,
            out,
        )
        rc, out = run([installer, "--home", d, "install"], ROOT)
        fails += check(
            "installer: removes a retired canonical skill link",
            rc == 0 and not os.path.lexists(stale)
            and "UNLINK stale canonical skill" in out,
            out,
        )

        tampered = os.path.join(d, ".agents", "skills", "codemap")
        os.unlink(tampered)
        os.symlink("../wrong-target", tampered)
        rc, out = run([installer, "--home", d, "check"], ROOT)
        fails += check(
            "installer: detects a non-canonical discovery link",
            rc == 1 and "codemap: not canonical" in out,
            out,
        )

        tampered_tool = os.path.join(d, ".codex", "bin", "cleanup-files")
        os.unlink(tampered_tool)
        os.symlink("../wrong-target", tampered_tool)
        rc, out = run([installer, "--home", d, "check"], ROOT)
        fails += check(
            "installer: detects a non-canonical tool link",
            rc == 1 and "cleanup-files: not canonical" in out,
            out,
        )

    with tempdir() as d:
        collision = os.path.join(d, ".agents", "skills", "codemap")
        os.makedirs(collision)
        with open(os.path.join(collision, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: unrelated\n---\n")
        installer = os.path.join(TOOLS, "install_skills.py")
        rc, out = run([installer, "--home", d, "install", "--replace"], ROOT)
        fails += check(
            "installer: refuses an unrelated same-named directory",
            rc == 2 and "refusing to replace unrelated directory" in out,
            out,
        )

    print("shared-skills selftest: %s (%d check(s) failed)"
          % ("FAILED" if fails else "PASSED", fails))
    return fails


if __name__ == "__main__":
    sys.exit(main())
