#!/usr/bin/env python3
"""Stand-in for an LLM worker: the task file's first line is a script for what to do.

The runner writes the prompt to a file and passes its path in argv, so a task
larger than the 128 KiB argv limit reaches the worker whole.

write <file> <text>          create <file> in the cwd
retry <file>                 write "bad" first; "good" once the task carries gate feedback
sleep <seconds>              sleep, then write nothing
orphan <pidfile>             spawn a long-lived child, record its PID, then hang
detach <pidfile> [hang]      start a setsid daemon (a session of its own), record its PID,
                             write detach.txt, then exit, or hang if asked
fail <code>                  exit with <code>
overlap <eventfile> <sec>    append start/end stamps around a sleep, then write a file
noop                         change nothing
envpwd                       write pwd.txt under $PWD (must be the worktree)
attached                     write attached.txt naming whether every attachment is absolute and in cwd
ledger <dir> <out>           write the reserve_mib of every entry in <dir> to <out> as JSON, then h.txt
resume <file>                append 'resumed' to <file> when the task says it was interrupted, else write 'fresh'
say <anything>               copy the whole task file to task.txt, so its size can be checked
"""

import os
import subprocess
import sys
import time

# The runner attaches the task file first, then the job's files; a real worker
# reads its task from that file, never from argv.
task_file, *attachments = sys.argv[1:]
with open(task_file, encoding="utf-8") as task:
    prompt = task.read()
words = prompt.splitlines()[0].split()
action = words[0]
if action == "write":
    with open(words[1], "w", encoding="utf-8") as out:
        out.write(words[2] + "\n")
elif action == "retry":
    content = "good" if "rejected by the gate" in prompt else "bad"
    with open(words[1], "w", encoding="utf-8") as out:
        out.write(content + "\n")
elif action == "sleep":
    time.sleep(float(words[1]))
elif action == "orphan":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(words[1], "w", encoding="utf-8") as out:
        out.write(str(child.pid))
    time.sleep(120)
elif action == "detach":
    daemon = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with open(words[1], "w", encoding="utf-8") as out:
        out.write(str(daemon.pid))
    with open("detach.txt", "w", encoding="utf-8") as out:
        out.write("detached\n")
    if words[2:] == ["hang"]:
        time.sleep(120)
elif action == "fail":
    sys.exit(int(words[1]))
elif action == "overlap":
    with open(words[1], "a", encoding="utf-8") as events:
        events.write(f"+ {time.time()}\n")
    time.sleep(float(words[2]))
    with open(words[1], "a", encoding="utf-8") as events:
        events.write(f"- {time.time()}\n")
    with open("overlap.txt", "w", encoding="utf-8") as out:
        out.write("done\n")
elif action == "envpwd":
    with open(os.path.join(os.environ["PWD"], "pwd.txt"), "w", encoding="utf-8") as out:
        out.write("pwd\n")
elif action == "attached":
    attached = attachments
    here = os.getcwd()
    fine = bool(attachments) and all(
        os.path.isabs(a) and a.startswith(here + os.sep) and os.path.isfile(a)
        for a in attached
    )
    with open("attached.txt", "w", encoding="utf-8") as out:
        out.write(("ok" if fine else "bad " + " ".join(attached)) + "\n")
elif action == "ledger":
    import json
    import pathlib

    rows = [json.loads(p.read_text()) for p in pathlib.Path(words[1]).glob("*.json")]
    pathlib.Path(words[2]).write_text(json.dumps([row["reserve_mib"] for row in rows]))
    with open("h.txt", "w", encoding="utf-8") as out:
        out.write("x\n")
elif action == "resume":
    if "interrupted part-way" in prompt:
        with open(words[1], "a", encoding="utf-8") as out:
            out.write("resumed\n")
    else:
        with open(words[1], "w", encoding="utf-8") as out:
            out.write("fresh\n")
elif action == "say":
    with open("task.txt", "w", encoding="utf-8") as out:
        out.write(prompt)
elif action == "noop":
    pass
else:
    sys.exit(f"unknown action {action}")
