#!/usr/bin/env python3
"""Stand-in for an LLM worker: the prompt's first line is a script for what to do.

write <file> <text>          create <file> in the cwd
retry <file>                 write "bad" first; "good" once the prompt carries gate feedback
sleep <seconds>              sleep, then write nothing
orphan <pidfile>             spawn a long-lived child, record its PID, then hang
fail <code>                  exit with <code>
overlap <eventfile> <sec>    append start/end stamps around a sleep, then write a file
noop                         change nothing
envpwd                       write pwd.txt under $PWD (must be the worktree)
attached                     write attached.txt naming whether every attachment is absolute and in cwd
"""

import os
import subprocess
import sys
import time

prompt = sys.argv[-1]
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
    attached = sys.argv[1:-1]
    here = os.getcwd()
    fine = attached and all(
        os.path.isabs(a) and a.startswith(here + os.sep) and os.path.isfile(a)
        for a in attached
    )
    with open("attached.txt", "w", encoding="utf-8") as out:
        out.write(("ok" if fine else "bad " + " ".join(attached)) + "\n")
elif action == "noop":
    pass
else:
    sys.exit(f"unknown action {action}")
