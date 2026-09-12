---
name: safe-kill
description: >-
  Safely kill or clean up OS processes from a Bash command without the `pkill -f` / `pgrep -f`
  self-match trap that SIGKILLs the shell running the command (truncating output, wasting context).
  Use whenever you need to terminate a process you launched — a backgrounded test/server/game
  instance, a stuck binary, leftover processes — or are tempted to reach for pkill/pgrep. Bundles a
  `safekill` helper script. Global / project-agnostic.
---

# Safely killing processes by PID

## The trap (why this skill exists)
Tool commands run inside a shell whose full command line contains the command
text. `pkill -f` and `pgrep -f` can match that wrapper itself. Killing by a
shared executable name can also stop another agent's or the user's process.
Capture or verify the exact PID instead.

## What to do instead (in order of preference)
1. **Kill by the PID you launched.** When you background a process, capture and kill that exact PID:
   ```bash
   mybin … &                 # or: ( … ) &
   P=$!
   …                         # do the work
   kill "$P" 2>/dev/null      # kills exactly what you started
   ```
   Or job control: `kill %1`.
2. **Let it exit on its own.** A backgrounded REPL/server you piped `quit\n` into, or a `timeout … cmd`,
   will end without any kill. Prefer this — no cleanup command at all.
3. **When the launch PID was lost, inspect process details** with
   `ps -eo pid,etimes,args`, distinguish the owned process from other runs, and
   pass only the verified PID to `safekill`.

## The `safekill` helper (bundled here)
`<skill-dir>/safekill` excludes itself and its ancestor chain:
```bash
SK=<skill-dir>/safekill
"$SK" -p 12345 23456     # kill only verified PIDs
```
First run may need `chmod +x "$SK"`.
