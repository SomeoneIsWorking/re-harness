---
name: safe-kill
description: >-
  Safely kill or clean up OS processes from a Bash command without the `pkill -f` / `pgrep -f`
  self-match trap that SIGKILLs the shell running the command (truncating output, wasting context).
  Use whenever you need to terminate a process you launched — a backgrounded test/server/game
  instance, a stuck binary, leftover processes — or are tempted to reach for pkill/pgrep. Bundles a
  `safekill` helper script. Global / project-agnostic.
---

# Safely killing processes (never `pkill -f` / `pgrep -f`)

## The trap (why this skill exists)
Your Bash tool command runs as `zsh -c '<the ENTIRE command text>'`. So any pattern you type is also
present in that **wrapper shell's own command line**. `pkill -f <pat>` and `pgrep -f <pat>` match the
*full command line*, so they match — and SIGKILL — the very shell running your command. The command dies
mid-run (output truncates, exit code 1, later steps like `git commit` never execute). This recurs and
burns context. **Hard rule: never use `-f` with pkill/pgrep.**

## What to do instead (in order of preference)
1. **Kill by the PID you launched.** When you background a process, capture and kill that exact PID:
   ```bash
   mybin … &                 # or: ( … ) &
   P=$!
   …                         # do the work
   kill -9 "$P" 2>/dev/null   # kills exactly what you started — zero collateral
   ```
   Or job control: `kill %1`.
2. **Let it exit on its own.** A backgrounded REPL/server you piped `quit\n` into, or a `timeout … cmd`,
   will end without any kill. Prefer this — no cleanup command at all.
3. **Match by process NAME, not command line.** `pkill <name>` (NO `-f`) matches `comm` (the executable
   name, ≤15 chars), so the `zsh`/`Codex` wrapper never matches unless you literally pass its name.
   Safer still, use the bundled `safekill` which also excludes self + ancestors.

## The `safekill` helper (bundled here)
`<skill-dir>/safekill` — kill by name (NAME match only, never `-f`) or by PID, always excluding this
script and its whole ancestor chain (shell → wrapper → Codex):
```bash
SK=<skill-dir>/safekill
"$SK" -p 12345 23456     # kill exactly these PIDs (the safest form)
"$SK" tomba2_port        # kill procs whose NAME matches (excludes self/ancestors); never -f
"$SK" -n tomba2_port     # DRY RUN: list what would be killed, kill nothing
```
First run may need `chmod +x "$SK"`.

## Quick reference
- ❌ `pkill -f tomba2_port`   → kills your own wrapper shell.
- ❌ `pgrep -f "foo bar"`     → matches your wrapper shell; piping its PIDs to `kill` nukes the command.
- ✅ `kill -9 "$P"` (captured `$!`) · `kill %1` · `pkill tomba2_port` (name) · `safekill …`.
