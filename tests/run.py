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

import contextlib
import json
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
SCRATCH = os.path.join(ROOT, "scratch", "tests")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, TOOLS)
import source_boundary  # noqa: E402
import install_skills  # noqa: E402
import cpp_policy  # noqa: E402
import libclang_ast  # noqa: E402


@contextlib.contextmanager
def environment(**values):
    """Run a block with these variables set, and leave the process as it was."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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


def scratch_gc_checks():
    """A marked provisioned tree survives a sweep that removes everything else."""
    import scratch_gc

    root = tempfile.mkdtemp(dir=SCRATCH)
    scratch = os.path.join(root, "project", "scratch")
    provisioned = os.path.join(scratch, "assets", "disc")
    probe = os.path.join(scratch, "probe")
    os.makedirs(provisioned)
    os.makedirs(probe)
    for path in (
        os.path.join(scratch, "assets", scratch_gc.KEEP_MARKER),
        os.path.join(provisioned, "GAME.EXE"),
        os.path.join(probe, "run.log"),
    ):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
    with contextlib.redirect_stdout(io.StringIO()):
        refused = scratch_gc.main([scratch, "--days", "0", "--apply", "--repo-root", root])
        rc = scratch_gc.main([scratch, "--days", "0", "--apply", "--whole-tree", "--repo-root", root])
    fails = check(
        "scratch_gc: a .scratch-keep tree survives --days 0",
        rc == 0 and os.path.isfile(os.path.join(provisioned, "GAME.EXE")),
    )
    fails += check("scratch_gc: a whole scratch tree needs --whole-tree", refused == 2)
    os.makedirs(probe, exist_ok=True)
    with open(os.path.join(probe, "late.log"), "w", encoding="utf-8") as handle:
        handle.write("x")
    with contextlib.redirect_stdout(io.StringIO()):
        activity_rc = scratch_gc.main([probe, "--days", "0", "--apply", "--repo-root", root])
    fails += check(
        "scratch_gc: scratch/<activity> sweeps without --whole-tree",
        activity_rc == 0 and not os.path.exists(os.path.join(probe, "late.log")),
    )
    fails += check(
        "scratch_gc: unmarked scratch is still swept",
        not os.path.exists(os.path.join(probe, "run.log")),
    )
    shutil.rmtree(root)
    return fails


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

    tidy_checks = ",".join(sorted(cpp_policy.REQUIRED_TIDY_CHECKS))
    tidy_config = (
        f"Checks: '{tidy_checks}'\nWarningsAsErrors: '*'\n"
        "  readability-braces-around-statements.ShortStatementLines: '0'\n"
    )
    format_config = "\n".join(
        f"{name}: {value}" for name, value in cpp_policy.REQUIRED_FORMAT_SETTINGS.items()
    )
    fails += check("cpp_policy: accepts required effective Clang config",
                   not cpp_policy.inspect_configs(tidy_config, format_config))
    quoted_tidy_config = tidy_config.replace(
        f"Checks: '{tidy_checks}'",
        f'Checks: "{tidy_checks}\\n"',
    )
    fails += check("cpp_policy: accepts Clang's escaped Checks scalar",
                   not cpp_policy.inspect_configs(quoted_tidy_config, format_config))
    nested_format_config = format_config.replace(
        "AllowShortFunctionsOnASingleLine: None",
        "AllowShortFunctionsOnASingleLine:\n  Empty: false\n  Inline: false\n  Other: false",
    )
    fails += check("cpp_policy: accepts equivalent nested short-function settings",
                   not cpp_policy.inspect_configs(tidy_config, nested_format_config))
    fails += check("cpp_policy: accepts legacy false short-function spelling",
                   not cpp_policy.inspect_configs(
                       tidy_config,
                       format_config.replace("AllowShortFunctionsOnASingleLine: None",
                                             "AllowShortFunctionsOnASingleLine: false"),
                   ))
    fails += check("cpp_policy: rejects nested short-function opt-in",
                   any("AllowShortFunctionsOnASingleLine" in finding for finding in
                       cpp_policy.inspect_configs(
                           tidy_config,
                           nested_format_config.replace("Inline: false", "Inline: true"),
                       )))
    rejected = cpp_policy.inspect_configs(
        tidy_config.replace("clang-diagnostic-*", "-*")
        .replace("WarningsAsErrors: '*'", "WarningsAsErrors: ''"),
        format_config.replace("InsertBraces: true", "InsertBraces: false"),
    )
    fails += check("cpp_policy: rejects disabled defaults and brace policy",
                   len(rejected) >= 4, "\n".join(rejected))
    clang_cl_args = cpp_policy.compile_arguments({"arguments": [
        "clang-cl", "/TP", "/c", "/Foobj\\unit.obj", "/Fdobj\\unit.pdb",
        "-c", "--", "unit.cpp",
    ]})
    fails += check(
        "cpp_policy: clang-cl AST scan drops output flags",
        clang_cl_args == ["clang-cl", "/TP", "unit.cpp"],
        repr(clang_cl_args),
    )
    fails += check(
        "cpp_policy: an explicit ccache launcher is dropped",
        cpp_policy.without_launcher(["ccache", "clang++", "-c", "unit.cpp"])
        == ["clang++", "-c", "unit.cpp"],
    )
    with tempfile.TemporaryDirectory() as tmp:
        masquerade = Path(tmp) / "ccache"
        real = Path(tmp) / "bin"
        masquerade.mkdir()
        real.mkdir()
        for directory in (masquerade, real):
            (directory / "clang++").write_text("#!/bin/sh\n")
            (directory / "clang++").chmod(0o755)
        resolved = cpp_policy.without_launcher(
            [str(masquerade / "clang++"), "-c", "unit.cpp"],
            search_path=os.pathsep.join([str(masquerade), str(real)]),
        )
        fails += check(
            "cpp_policy: a ccache masquerade link resolves to the compiler behind it",
            resolved == [str(real / "clang++"), "-c", "unit.cpp"],
            repr(resolved),
        )
    if os.name == "nt":
        windows_command = (
            r'"C:\Program Files\LLVM\bin\clang-cl.exe" /TP /c -- '
            r'D:\a\jit-common\src\block_cache.cpp'
        )
        fails += check(
            "cpp_policy: Windows command string preserves backslash paths",
            cpp_policy.split_compile_command(windows_command) == [
                r"C:\Program Files\LLVM\bin\clang-cl.exe", "/TP", "/c", "--",
                r"D:\a\jit-common\src\block_cache.cpp",
            ],
        )
    gcc_args = cpp_policy.compile_arguments({"arguments": ["/usr/bin/g++-14", "-c", "unit.cpp"]})
    fails += check(
        "cpp_policy: a GCC compile command is read through Clang",
        shutil.which("clang++") is None or Path(gcc_args[0]).name.startswith("clang++"),
        repr(gcc_args),
    )
    jobs_default = cpp_policy.scan_workers(64)
    with environment(CPP_POLICY_JOBS="3"):
        jobs_named = cpp_policy.scan_workers(64)
        jobs_capped = cpp_policy.scan_workers(2)
    with environment(CPP_POLICY_JOBS="0"):
        try:
            cpp_policy.scan_workers(4)
        except ValueError as error:
            jobs_refused = str(error)
        else:
            jobs_refused = ""
    fails += check(
        "cpp_policy: scans units in parallel and lets a caller say how many",
        jobs_default > 1 and jobs_named == 3 and jobs_capped == 2 and "at least 1" in jobs_refused,
        f"{jobs_default} {jobs_named} {jobs_capped} {jobs_refused!r}",
    )

    # C++ ownership checks use the shipping Clang AST path, including headers.
    clang = shutil.which("clang++")
    fails += check("cpp_policy: Clang AST compiler available", clang is not None)
    if clang:
        with tempdir() as project:
            good = os.path.join(project, "good.cpp")
            bad = os.path.join(project, "bad.cpp")
            c_source = os.path.join(project, "unrelated.c")
            header = os.path.join(project, "api.h")
            with open(good, "w", encoding="utf-8") as target:
                target.write(
                    "namespace demo { inline constexpr int limit = 2; "
                    "class Worker { public: int run() { const int value = limit; return value; } }; }\n"
                    "int main() { demo::Worker worker; const int* ptr = nullptr; constexpr int once = 1; "
                    "const int& ref = demo::limit; (void)ptr; (void)ref; (void)once; "
                    "return worker.run() - 2; }\n"
                )
            with open(header, "w", encoding="utf-8") as target:
                target.write("extern int shared;\n")
            with open(c_source, "w", encoding="utf-8") as target:
                target.write("int c_global(void) { return 0; }\n")
            with open(bad, "w", encoding="utf-8") as target:
                target.write(
                    '#include "api.h"\n'
                    "int x2_run() { static int count = 0; const int step = 1; return count + step; }\n"
                    'extern "C" int platform_api(int value) { return value; }\n'
                )
            database = os.path.join(project, "compile_commands.json")
            with open(database, "w", encoding="utf-8") as target:
                json.dump([
                    {
                        "directory": project,
                        "file": good,
                        "arguments": [clang, "-std=c++20", "-c", good, "-o", "good.o"],
                    },
                    {
                        "directory": project,
                        "file": c_source,
                        "arguments": [clang, "-c", c_source, "-o", "unrelated.o"],
                    },
                ], target)
            command = [os.path.join(TOOLS, "cpp_policy.py"),
                       "--compile-commands", database, "--root", project]
            rc, output = run(command, project)
            fails += check("cpp_policy: accepts namespaced class, entry point, and const locals",
                           rc == 0 and "scanned 1 translation units" in output
                           and "0 violations" in output, output)
            with open(database, "w", encoding="utf-8") as target:
                json.dump([{
                    "directory": project,
                    "file": bad,
                    "arguments": [clang, "-std=c++20", "-c", bad, "-o", "bad.o"],
                }], target)
            rc, output = run(command, project)
            expected = ("api.h:1: extern declaration", "bad.cpp:2: global-namespace function",
                        "bad.cpp:2: block-scope static")
            fails += check("cpp_policy: rejects header extern and bad local ownership",
                           rc == 1 and all(item in output for item in expected)
                           and "platform_api" not in output
                           and "block-scope const" not in output, output)
            accepted = os.path.join(project, "accepted.txt")
            with open(accepted, "w", encoding="utf-8") as target:
                target.write(
                    "# the boundary this project owns\n"
                    "api.h:extern declaration:shared\n"
                    "bad.cpp:global-namespace function:x2_run\n"
                    "bad.cpp:block-scope static:count\n"
                )
            rc, output = run(command + ["--accept", accepted], project)
            fails += check("cpp_policy: accepts the sites a project has named",
                           rc == 0 and "3 accepted sites" in output
                           and "0 violations" in output, output)
            with open(accepted, "a", encoding="utf-8") as target:
                target.write("bad.cpp:block-scope static:long_gone\n")
            rc, output = run(command + ["--accept", accepted], project)
            fails += check("cpp_policy: reports an accepted site that no longer occurs",
                           rc == 1 and "no longer occurs" in output
                           and "long_gone" in output, output)

            # Entry points: with entry roots named, `main` is a finding anywhere else.
            entry_dir = os.path.join(project, "tests")
            os.makedirs(entry_dir)
            in_root = os.path.join(entry_dir, "test_unit.cpp")
            launcher = os.path.join(project, "launcher.cpp")
            for path in (in_root, launcher):
                with open(path, "w", encoding="utf-8") as target:
                    target.write("int main() { return 0; }\n")
            with open(database, "w", encoding="utf-8") as target:
                json.dump([
                    {"directory": project, "file": path,
                     "arguments": [clang, "-std=c++20", "-c", path, "-o", "unit.o"]}
                    for path in (in_root, launcher)
                ], target)
            entry_command = command + ["--entry-root", "tests"]
            rc, output = run(entry_command, project)
            fails += check("cpp_policy: rejects main outside the entry roots",
                           rc == 1 and "launcher.cpp:1: entry point: main" in output
                           and "test_unit.cpp" not in output, output)
            with open(accepted, "w", encoding="utf-8") as target:
                target.write("# packaging launcher, folded into the product later\n"
                             "launcher.cpp:entry point:main\n")
            rc, output = run(entry_command + ["--accept", accepted], project)
            fails += check("cpp_policy: accepts a named hand-written main",
                           rc == 0 and "1 accepted sites" in output
                           and "0 violations" in output, output)
            rc, output = run(entry_command + ["--entry-root", "launcher.cpp", "--accept", accepted],
                             project)
            fails += check("cpp_policy: an accepted main inside an entry root no longer occurs",
                           rc == 1 and "no longer occurs: launcher.cpp:entry point:main" in output,
                           output)
            rc, output = run(command, project)
            fails += check("cpp_policy: main is an entry point anywhere without entry roots",
                           rc == 0 and "0 violations" in output, output)

            # Retired names: a use of a named global function outside the entry roots is a finding,
            # resolved through the AST, so a namespaced function of the same name and a comment are not.
            with open(header, "w", encoding="utf-8") as target:
                target.write('extern "C" void old_bind(int* core);\n'
                             "namespace demo { inline void old_bind(int*) {} }\n")
            # A framework header outside the root declares a C++-linkage one.
            framework = os.path.join(project, "framework")
            os.makedirs(framework)
            with open(os.path.join(framework, "legacy.h"), "w", encoding="utf-8") as target:
                target.write("void old_init();\n")
            product = os.path.join(project, "product.cpp")
            harness_use = os.path.join(entry_dir, "test_bind.cpp")
            with open(product, "w", encoding="utf-8") as target:
                target.write('#include "api.h"\n'
                             '#include "framework/legacy.h"\n'
                             "namespace demo { void boot(int* core) {\n"
                             "  // old_bind(core) is what this used to call\n"
                             "  demo::old_bind(core);\n"
                             "  ::old_bind(core);\n"
                             "  old_init(); } }\n")
            with open(harness_use, "w", encoding="utf-8") as target:
                target.write('#include "../api.h"\n'
                             "namespace demo { void fixture(int* core) { ::old_bind(core); } }\n")
            with open(database, "w", encoding="utf-8") as target:
                json.dump([
                    {"directory": project, "file": path,
                     "arguments": [clang, "-std=c++20", "-c", path, "-o", "unit.o"]}
                    for path in (product, harness_use)
                ], target)
            retired_command = command + ["--entry-root", "tests", "--exclude", "framework",
                                         "--retired-name", "old_bind", "--retired-name", "old_init"]
            rc, output = run(retired_command, project)
            fails += check("cpp_policy: rejects a retired name outside the entry roots",
                           rc == 1 and "product.cpp:6: retired name: old_bind" in output
                           and "product.cpp:7: retired name: old_init" in output
                           and "product.cpp:5" not in output and "product.cpp:4" not in output
                           and "test_bind.cpp" not in output, output)
            rc, output = run(command + ["--entry-root", "tests", "--exclude", "framework"], project)
            fails += check("cpp_policy: a name nobody retired is not a finding",
                           rc == 0 and "0 violations" in output, output)
            with open(accepted, "w", encoding="utf-8") as target:
                target.write("# a title still on its own boot\nproduct.cpp:retired name:old_bind\n"
                             "product.cpp:retired name:old_init\n")
            rc, output = run(retired_command + ["--accept", accepted], project)
            fails += check("cpp_policy: accepts a named retired-name site",
                           rc == 0 and "2 accepted sites" in output, output)

            # Sites through macro arguments, templates and lambdas; a using-declaration of a
            # namespaced function, or its qualified definition at file scope, is not a global function.
            with open(header, "w", encoding="utf-8") as target:
                target.write(
                    "#define KEEP(name) static int name = 0\n"
                    "#define CHECK(x) (void)(x)\n"
                    "namespace demo { inline int helper() { return 1; } }\n"
                )
            shapes = os.path.join(project, "shapes.cpp")
            with open(shapes, "w", encoding="utf-8") as target:
                target.write(
                    '#include "api.h"\n'
                    "using demo::helper;\n"
                    "namespace demo { int outer() { CHECK(helper()); KEEP(kept); return kept; } }\n"
                    "template <class T> T twice(T value) { return value + value; }\n"
                    "namespace demo { int lambda() { auto make = [] { static int inner = 0; return inner; };"
                    " return make(); } }\n"
                    "namespace demo { int qualified(); }\n"
                    "int demo::qualified() { return 0; }\n"
                )
            with open(database, "w", encoding="utf-8") as target:
                json.dump([{
                    "directory": project,
                    "file": shapes,
                    "arguments": [clang, "-std=c++20", "-c", shapes, "-o", "shapes.o"],
                }], target)
            rc, output = run(command, project)
            expected = ("shapes.cpp:3: block-scope static: kept", "shapes.cpp:4: global-namespace function: twice",
                        "shapes.cpp:5: block-scope static: inner")
            fails += check("cpp_policy: finds sites through macros, templates and lambdas",
                           rc == 1 and all(item in output for item in expected)
                           and "helper" not in output and "qualified" not in output
                           and "3 violations" in output, output)

            # The cache: an unchanged unit is reused, and a header edit rescans only its includers.
            other = os.path.join(project, "other.cpp")
            with open(other, "w", encoding="utf-8") as target:
                target.write('#include "lib.h"\n#if __has_include("late.h")\n#include "late.h"\n#endif\n'
                             "namespace demo { int other() { return 0; } }\n")
            for name in ("early", "late"):
                os.makedirs(os.path.join(project, name))
            with open(os.path.join(project, "late", "lib.h"), "w", encoding="utf-8") as target:
                target.write("namespace demo { inline int lib() { return 0; } }\n")
            with open(database, "w", encoding="utf-8") as target:
                json.dump([
                    {"directory": project, "file": path,
                     "arguments": [clang, "-std=c++20", "-Iearly", "-Ilate", "-c", path, "-o", Path(path).stem + ".o"]}
                    for path in (shapes, other)
                ], target)

            def settle():
                # Sources older than the scan, as an edited tree is by the time a gate runs.
                settled = time.time() - 60
                for base, _, names in os.walk(project):
                    for path in [base, *(os.path.join(base, name) for name in names)]:
                        os.utime(path, (settled, settled))

            settle()
            rc, first = run(command, project)
            rc, second = run(command, project)
            cache_dir = os.path.join(project, cpp_policy.CACHE_DIRECTORY)
            fails += check("cpp_policy: reuses every unchanged unit from the cache",
                           "(0 unchanged since the last scan)" in first
                           and "(2 unchanged since the last scan)" in second
                           and first.splitlines()[1:] == second.splitlines()[1:]
                           and len(os.listdir(cache_dir)) == 2, first + second)
            with open(header, "a", encoding="utf-8") as target:
                target.write("extern int added;\n")
            rc, edited = run(command, project)
            fails += check("cpp_policy: a header edit rescans only the units that include it",
                           "(1 unchanged since the last scan)" in edited
                           and "api.h:4: extern declaration: added" in edited, edited)
            settle()
            run(command, project)
            with open(os.path.join(project, "early", "lib.h"), "w", encoding="utf-8") as target:
                target.write("int shadowing() { return 0; }\n")
            rc, shadowed = run(command, project)
            fails += check("cpp_policy: a header that shadows an included one rescans its includers",
                           "lib.h:1: global-namespace function: shadowing" in shadowed, shadowed)
            settle()
            run(command, project)
            with open(os.path.join(project, "late.h"), "w", encoding="utf-8") as target:
                target.write("int arrived() { return 0; }\n")
            rc, arrived = run(command, project)
            fails += check("cpp_policy: a header a __has_include now finds rescans the unit asking",
                           "late.h:1: global-namespace function: arrived" in arrived, arrived)

            # A unit Clang cannot compile fails the scan with Clang's own diagnostics.
            with open(other, "w", encoding="utf-8") as target:
                target.write("namespace demo { int broken( }\n")
            try:
                cpp_policy.check_database(cpp_policy.Path(database), cpp_policy.Path(project))
            except RuntimeError as error:
                compile_error = str(error)
            else:
                compile_error = ""
            fails += check("cpp_policy: reports a unit Clang cannot compile, with its diagnostics",
                           "AST compile failed for" in compile_error and "other.cpp" in compile_error
                           and "error:" in compile_error, compile_error)

        # A Clang without its matching libclang is refused with the install command, never
        # parsed by some other libclang that happens to be on the system.
        if os.name != "nt":
            with tempdir() as toolchain:
                fake = os.path.join(toolchain, "bin", "clang++")
                os.makedirs(os.path.dirname(fake))
                with open(fake, "w", encoding="utf-8") as target:
                    target.write("#!/bin/sh\necho 'clang version 999.1.0'\n")
                os.chmod(fake, 0o755)
                try:
                    libclang_ast.library_for(fake)
                except libclang_ast.LibclangMissing as error:
                    missing_error = str(error)
                else:
                    missing_error = ""
                fails += check("cpp_policy: refuses a Clang without its libclang, naming the install",
                               "no libclang 999" in missing_error and "dnf install clang-libs" in missing_error
                               and "libclang1-999" in missing_error, missing_error)

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
        expected = len(install_skills.discover()) * 3
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

    if sys.platform.startswith("linux"):
        sys.path.insert(0, HERE)
        import swarm_checks
        fails += swarm_checks.run_checks(check, SCRATCH)
    else:
        rc, out = run([os.path.join(TOOLS, "swarm.py"), "report", SCRATCH], ROOT)
        fails += check("swarm: refuses by name off Linux", rc == 1 and "Linux-only" in out, out)

    sys.path.insert(0, HERE)
    import play_checks
    fails += play_checks.run_checks(check, SCRATCH)

    fails += scratch_gc_checks()

    print("shared-skills selftest: %s (%d check(s) failed)"
          % ("FAILED" if fails else "PASSED", fails))
    return fails


if __name__ == "__main__":
    sys.exit(main())
