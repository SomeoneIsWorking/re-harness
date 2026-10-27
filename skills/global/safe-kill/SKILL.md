---
name: safe-kill
description: "Kill only the process you launched, by its captured PID, never by name or `pkill -f`/`pgrep -f` (which match your own shell and other agents' runs). Use for leftover test, server or game processes."
---

# Kill by PID

Tool commands run inside a shell whose command line contains the command text, so `pkill -f` and
`pgrep -f` can match that shell. Killing by executable name stops other agents' and the user's
processes too.

1. Capture the PID at launch and kill exactly that:
   ```bash
   mybin … &
   P=$!
   …
   kill "$P"
   ```
2. Prefer a process that ends on its own (`timeout … cmd`, piping `quit` into a REPL).
3. If the PID was lost, find it with `ps -eo pid,etimes,args`, confirm it is yours, and `kill <pid>`.
