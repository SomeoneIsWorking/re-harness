#!/usr/bin/env python3
"""re_frontier.py — the RE-frontier progress tracker.

The codemap (docs/codemap.md) answers "what subsystem is where + coarse status".
The issue catalog (docs/issues/) answers "did we hit this symptom before". Neither answers the
question this project keeps tripping on: **for the ordered chain of RE steps
toward a faithful behaviour, which step is real reverse-engineering vs a
render/behaviour HACK that jumped ahead of the RE?**

This tool tracks exactly that. It operates over a greppable markdown roadmap
(docs/re-frontier.md) — one entry per RE step, each with a status, its
dependencies (the RE that must land first), where the ground-truth evidence
lives, and the honest gap. It is zero-dependency (stdlib only).

WRITES ARE IN-PLACE SURGERY, NEVER A REGENERATION. The roadmap is a hand-written
document that happens to carry machine-readable fields: multi-paragraph
rationale, dated corrections, tables and "expires if" conditions live between the
entries and inside them. `add`/`set` therefore edit the exact lines they mean to
change and copy every other byte through untouched. Every write is gated on a
preservation check that compares the new text against the old and REFUSES (exit
2, naming the lost lines) if any content the edit did not explicitly intend to
replace would go missing.

Statuses (the core axis — real RE vs jumped-ahead hack):
  re-verified   RE'd from ground truth (exe / cooked data) + implemented + VERIFIED on real data
  re-partial    real RE, but a documented honest gap remains
  in-progress   actively being RE'd/implemented, not yet verified
  hack          a shortcut standing in for absent RE -- DEBT. Must be removed and
                replaced with the real mechanism (no-hacks / no-fallbacks hard rule).
  blocked       cannot start: a dependency's RE isn't done (usually COMPUTED, not stored)
  todo          not started
  skip-by-design deliberately not implemented (e.g. Bink startup movies)
  authored      not RE and never can be: a hand-made judgement the target does not hold

Commands:
  list [--area A] [--status S]   table of entries
  show <id>                      full entry
  next [--area A]                steps ready to work (all deps satisfied) + hacks to replace
  hacks                          every hack entry -- the debt list (no-hacks rule)
  blocked                        steps whose deps' RE isn't done yet
  tree [--area A]                dependency tree per area
  stats                          counts by status
  check                          integrity: unknown deps, cycles, missing fields; exit 1 on drift
  add <id> --title T --area A [--status S] [--deps a,b] [--evidence E] [--where W] [--gap G] [--notes N]
  set <id> field=value ...       update fields (status/deps/evidence/where/gap/notes/title/area)
"""
import argparse
import collections
import os
import re
import sys

# The roadmap is the working project's docs/re-frontier.md, or $RE_FRONTIER_ROADMAP.
ROADMAP = os.environ.get("RE_FRONTIER_ROADMAP", os.path.join(os.getcwd(), "docs", "re-frontier.md"))

STATUS_EMOJI = {
    "re-verified": "✅",
    "re-partial": "🟡",
    "in-progress": "🔬",
    "hack": "⛔",
    "todo": "⬜",
    "skip-by-design": "➖",
    "authored": "✍",
    "blocked": "⏸",  # computed
}
# Statuses that count as "the RE this step depends on is done enough to build on".
SATISFIED = {"re-verified", "re-partial", "skip-by-design", "authored"}
FIELDS = ["status", "area", "deps", "evidence", "where", "gap", "notes"]
BODY_FIELDS = ("status", "deps", "evidence", "where", "gap", "notes")
VALID_STATUS = set(STATUS_EMOJI) - {"blocked"}

HEADING_RE = re.compile(r"^#{1,6} ")
AREA_RE = re.compile(r"^## +(.+)$")
ENTRY_RE = re.compile(r"^### +(\S+) +(—|-) +(.+)$")
FIELD_RE = re.compile(r"^- +(\w+): ?(.*)$")
# An unknown field-shaped bullet (`- where-2: …`) stays in the field run and is never rewritten.
EXTRA_FIELD_RE = re.compile(r"^- +([\w-]+): ?(.*)$")

HEADER = """# RE Frontier — the ordered RE dependency chain toward a faithful port

Tracked by `tools/re_frontier.py` (consult it FIRST; update it in the SAME commit
that changes a step). This is the fine-grained companion to `docs/codemap.md`:
the codemap says *what subsystem exists*, this says *which ordered RE step is
real reverse-engineering vs a hack that jumped ahead*.

**Hard rule (no hacks / no fallbacks):** a `⛔ hack` status is DEBT, never an
acceptable resting state. It marks a shortcut standing in for absent RE and MUST
be removed as its real mechanism lands. `re_frontier.py hacks` is the debt list;
`re_frontier.py next` tells you the next RE-ready step.

**`re-verified` MEANS FAITHFUL to the real target — not "the mechanism runs."** A
step is `re-verified` only when its OUTPUT matches the real game/binary (look /
sound / behavior) on real data. An internal trace ("bytecode reached the call
site", "N rows attached") is a mechanism check, NOT faithfulness — if it runs but
the result doesn't match the real target, it is `re-partial` with the
faithfulness gap named. The user observes the running system; that observation
overrides any internal trace.

**Fail fast & loud:** a failure must surface loudly, never silently fall back —
unless the fallback IS intended behavior of the real target being reproduced.

Statuses: ✅ re-verified · 🟡 re-partial (honest gap) · 🔬 in-progress ·
⛔ hack (debt, must remove) · ⬜ todo · ➖ skip-by-design · ✍ authored · ⏸ blocked (computed).

<!-- Entries are `## <area>` sections holding `### <id> — <title>` headings, each
     followed by `- <field>: <value>` lines. Prose ANYWHERE in this file — before,
     between or inside entries — is yours: tools/re_frontier.py edits only the
     field lines it is told to change and copies everything else through byte for
     byte, refusing the write if anything else would be lost. -->
"""


class Entry:
    def __init__(self, eid, title, area):
        self.id = eid
        self.title = title
        self.area = area
        self.status = "todo"
        self.deps = []
        self.evidence = ""
        self.where = ""
        self.gap = ""
        self.notes = ""
        # Position in the source document (set by load(); None for entries the
        # caller just constructed).
        self.head_line = None      # index of the `### id — title` line
        self.block_end = None      # exclusive end of this entry's text block
        self.field_lines = {}      # field name -> line index
        self.extra_lines = []      # field-shaped lines with a key this tool doesn't know
        self.dash = "—"

    def field_block(self):
        """The `- field: value` lines for a NEW entry, in canonical order."""
        out = [f"- status: {self.status}", f"- deps: {', '.join(self.deps)}"]
        for f in ("evidence", "where", "gap", "notes"):
            out.append(f"- {f}: {getattr(self, f)}")
        return out

    def serialize(self):
        return "\n".join([f"### {self.id} {self.dash} {self.title}"] + self.field_block())


class Doc:
    """The roadmap as raw text plus the positions the parser recognised.

    Everything the parser did NOT recognise is still in `lines`, which is what
    the writers copy through.
    """

    def __init__(self, path):
        self.path = path
        self.lines = []
        self.trailing_newline = True
        self.exists = False
        self.area_lines = {}   # area name -> index of its `## area` heading

    def area_section_end(self, area):
        """Index just past the last line belonging to `## area`."""
        start = self.area_lines[area]
        for i in range(start + 1, len(self.lines)):
            if AREA_RE.match(self.lines[i]) or re.match(r"^# ", self.lines[i]):
                return i
        return len(self.lines)


DOC = Doc(ROADMAP)


def load(path=None):
    """Parse the roadmap into {id: Entry}, keeping the raw text in DOC."""
    global DOC
    DOC = Doc(path or ROADMAP)
    entries, order = {}, []
    if not os.path.exists(DOC.path):
        return entries, order
    DOC.exists = True
    with open(DOC.path, encoding="utf-8") as fh:
        text = fh.read()
    DOC.trailing_newline = text.endswith("\n")
    DOC.lines = text.split("\n")
    if DOC.trailing_newline:
        DOC.lines.pop()

    area = "misc"
    for i, line in enumerate(DOC.lines):
        m = AREA_RE.match(line)
        if m and not line.startswith("### "):
            area = m.group(1).strip()
            DOC.area_lines.setdefault(area, i)
            continue
        m = ENTRY_RE.match(line)
        if not m:
            continue
        e = Entry(m.group(1).strip(), m.group(3).strip(), area)
        e.dash = m.group(2)
        e.head_line = i
        # Fields are the CONTIGUOUS run of `- field: value` lines directly under
        # the heading. Anything after the first non-field line is prose and is
        # never touched — a `- note: ...` inside a paragraph is not a field.
        j = i + 1
        while j < len(DOC.lines):
            fm = EXTRA_FIELD_RE.match(DOC.lines[j])
            if not fm:
                break
            key, val = fm.group(1), fm.group(2).strip()
            if key not in BODY_FIELDS:
                e.extra_lines.append(DOC.lines[j])   # kept, never rewritten
            elif key not in e.field_lines:    # first wins; duplicates stay as text
                e.field_lines[key] = j
                if key == "deps":
                    e.deps = [d.strip() for d in val.split(",") if d.strip()]
                else:
                    setattr(e, key, val)
            j += 1
        # The block runs to the next entry heading or the next area heading.
        # Unrecognised `###` prose headings stay INSIDE the block, because they
        # are this entry's rationale.
        k = j
        end = len(DOC.lines)
        while k < len(DOC.lines):
            if AREA_RE.match(DOC.lines[k]) and not DOC.lines[k].startswith("### "):
                end = k
                break
            if ENTRY_RE.match(DOC.lines[k]) or re.match(r"^# ", DOC.lines[k]):
                end = k
                break
            k += 1
        e.block_end = end
        entries[e.id] = e
        order.append(e.id)
    return entries, order


# ---------------------------------------------------------------- writing ----

class PreservationError(Exception):
    def __init__(self, lost):
        super().__init__("write would lose content")
        self.lost = lost           # list of (old_line_no, count, text)


def _check_preserved(old_lines, new_lines, intended_drops):
    """Refuse any write that loses text the edit did not intend to replace.

    This is deliberately INDEPENDENT of how the new text was built: it compares
    multisets of non-blank lines, so a bug in the editing code shows up here as a
    refusal rather than as a silent deletion. `intended_drops` is the exact list
    of old lines the caller replaced or removed on purpose.
    """
    need = collections.Counter(l for l in old_lines if l.strip())
    need.subtract(collections.Counter(l for l in intended_drops if l.strip()))
    have = collections.Counter(l for l in new_lines if l.strip())
    lost = []
    for line, n in need.items():
        deficit = n - have.get(line, 0)
        if deficit > 0:
            try:
                first = old_lines.index(line) + 1
            except ValueError:
                first = 0
            lost.append((first, deficit, line))
    if lost:
        raise PreservationError(sorted(lost))
    # Denominator: total non-blank line OCCURRENCES that had to survive (not
    # distinct lines — a roadmap repeats `- where:` dozens of times).
    return sum(n for n in need.values() if n > 0)


def commit(new_lines, intended_drops, what):
    """Verify then write. Prints the denominator; exits 2 on any loss."""
    old = DOC.lines
    try:
        checked = _check_preserved(old, new_lines, intended_drops)
    except PreservationError as ex:
        print(f"REFUSING TO WRITE {DOC.path}: the edit would lose "
              f"{len(ex.lost)} line(s) it did not intend to change:", file=sys.stderr)
        for lineno, count, text in ex.lost[:40]:
            where = f"old line {lineno}" if lineno else "old text"
            print(f"  {where}{' x%d' % count if count > 1 else ''}: {text[:160]}",
                  file=sys.stderr)
        if len(ex.lost) > 40:
            print(f"  … and {len(ex.lost) - 40} more", file=sys.stderr)
        print("Nothing was written. This is a bug in re_frontier.py's editor — the "
              "roadmap is unchanged; edit it by hand and report the failure.",
              file=sys.stderr)
        sys.exit(2)
    text = "\n".join(new_lines) + ("\n" if DOC.trailing_newline else "")
    with open(DOC.path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{what} ({DOC.path}: {len(old)} -> {len(new_lines)} lines; "
          f"{checked} non-blank lines required to survive, "
          f"{len(intended_drops)} intentionally replaced, 0 lost)")


def apply_field_edits(lines, e, updates):
    """Replace/insert only the field lines named in `updates`. Returns (lines, drops)."""
    lines = list(lines)
    drops = []
    inserts = []
    for key, val in updates:
        if key in e.field_lines:
            idx = e.field_lines[key]
            drops.append(lines[idx])
            lines[idx] = f"- {key}: {val}"
        elif val != "":
            anchor = max(e.field_lines.values()) if e.field_lines else e.head_line
            inserts.append((anchor + 1, f"- {key}: {val}"))
    for pos, text in sorted(inserts, key=lambda t: -t[0]):
        lines.insert(pos, text)
    return lines, drops


def rewrite_heading(lines, e, new_id, new_title):
    drops = [lines[e.head_line]]
    lines = list(lines)
    lines[e.head_line] = f"### {new_id} {e.dash} {new_title}"
    return lines, drops


def _block_bounds(lines, head_text):
    """Locate an entry block in a (possibly already edited) line list."""
    if lines.count(head_text) != 1:
        print(f"REFUSING: {lines.count(head_text)} lines read exactly {head_text!r}; "
              f"cannot tell which block to move. Fix the duplicate heading first.",
              file=sys.stderr)
        sys.exit(2)
    start = lines.index(head_text)
    end = len(lines)
    for k in range(start + 1, len(lines)):
        if ENTRY_RE.match(lines[k]) or re.match(r"^#{1,2} ", lines[k]):
            end = k
            break
    return start, end


def _area_insert_point(lines, area):
    """Index at which a new entry block goes for `area`; creates the section if absent."""
    lines = list(lines)
    head = None
    for i, l in enumerate(lines):
        m = AREA_RE.match(l)
        if m and not l.startswith("### ") and m.group(1).strip() == area:
            head = i
            break
    if head is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", f"## {area}", ""])
        return lines, len(lines)
    end = len(lines)
    for k in range(head + 1, len(lines)):
        if AREA_RE.match(lines[k]) and not lines[k].startswith("### "):
            end = k
            break
        if re.match(r"^# ", lines[k]):
            end = k
            break
    while end > head + 1 and not lines[end - 1].strip():
        end -= 1
    return lines, end


def move_entry_to_area(lines, head_text, area):
    """Move an entry's whole block (prose included) under a different `## area`."""
    start, end = _block_bounds(lines, head_text)
    block = lines[start:end]
    while block and not block[-1].strip():
        block.pop()
    rest = lines[:start] + lines[end:]
    rest, at = _area_insert_point(rest, area)
    return rest[:at] + [""] + block + rest[at:]


# ---------------------------------------------------------------- reading ----

def effective_status(e, entries):
    """A todo/in-progress step whose deps aren't all satisfied is BLOCKED."""
    if e.status in ("todo", "in-progress"):
        for d in e.deps:
            dep = entries.get(d)
            if dep is None or dep.status not in SATISFIED:
                return "blocked"
    return e.status


def emoji(status):
    return STATUS_EMOJI.get(status, "?")


def cmd_list(entries, order, args):
    for eid in order:
        e = entries[eid]
        if args.area and e.area != args.area:
            continue
        eff = effective_status(e, entries)
        if args.status and eff != args.status and e.status != args.status:
            continue
        print(f"{emoji(eff)} {e.status:<14} {eid:<34} {e.title}")


def cmd_show(entries, order, args):
    e = entries.get(args.id)
    if not e:
        print(f"no such entry: {args.id}", file=sys.stderr)
        return 1
    eff = effective_status(e, entries)
    print(f"### {e.id} — {e.title}")
    print(f"  area:     {e.area}")
    print(f"  status:   {emoji(e.status)} {e.status}" +
          (f"  (effective: {emoji(eff)} {eff})" if eff != e.status else ""))
    print(f"  deps:     {', '.join(e.deps) or '—'}")
    for d in e.deps:
        dep = entries.get(d)
        tag = f"{emoji(dep.status)} {dep.status}" if dep else "‼ UNKNOWN"
        print(f"              {d}: {tag}")
    print(f"  evidence: {e.evidence or '—'}")
    print(f"  where:    {e.where or '—'}")
    print(f"  gap:      {e.gap or '—'}")
    print(f"  notes:    {e.notes or '—'}")
    for extra in e.extra_lines:
        print(f"  (extra field this tool does not parse, kept verbatim) {extra}")
    prose =[l for l in DOC.lines[max(e.field_lines.values(), default=e.head_line) + 1:e.block_end]
             if l.strip()]
    if prose:
        print(f"  prose:    {len(prose)} non-blank line(s) of rationale in the roadmap "
              f"(lines {max(e.field_lines.values(), default=e.head_line) + 2}"
              f"..{e.block_end}) — read them before acting on the fields above")
    return 0


def cmd_next(entries, order, args):
    ready = []
    for eid in order:
        e = entries[eid]
        if args.area and e.area != args.area:
            continue
        if e.status in ("todo", "in-progress") and effective_status(e, entries) != "blocked":
            ready.append(e)
    print("== RE-ready steps (all deps satisfied) ==")
    if not ready:
        if not entries:
            print(f"  no entries parsed from {DOC.path}; run `check`")
        else:
            print(f"  (none of the {len(entries)} parsed step(s) is ready — each is either done or "
                  f"blocked on upstream RE)")
    for e in ready:
        print(f"  {emoji(e.status)} {e.id:<34} {e.title}")
        if e.gap:
            print(f"      gap: {e.gap}")
    hacks = [entries[i] for i in order if entries[i].status == "hack"
             and (not args.area or entries[i].area == args.area)]
    if hacks:
        print("\n== ⛔ hacks to REPLACE with real RE (no-hacks rule) ==")
        for e in hacks:
            print(f"  {e.id:<34} {e.title}")
            if e.gap:
                print(f"      real mechanism: {e.gap}")


def cmd_hacks(entries, order, args):
    hacks = [entries[i] for i in order if entries[i].status == "hack"]
    if not hacks:
        print(f"No hacks tracked among {len(order)} parsed entr(ies) in {DOC.path}. "
              f"(Good — no-hacks rule holds, for everything that carries a `- status:` "
              f"line; debt described only in prose is invisible here.)")
        return 0
    print(f"⛔ {len(hacks)} hack(s) — DEBT standing in for real RE, must be removed:\n")
    for e in hacks:
        print(f"  {e.id:<34} [{e.area}] {e.title}")
        if e.where:
            print(f"      where: {e.where}")
        if e.gap:
            print(f"      real mechanism: {e.gap}")
    return 0


def cmd_blocked(entries, order, args):
    for eid in order:
        e = entries[eid]
        if effective_status(e, entries) == "blocked":
            unmet = [d for d in e.deps
                     if d not in entries or entries[d].status not in SATISFIED]
            print(f"⏸ {eid:<34} {e.title}")
            print(f"      waiting on: {', '.join(unmet)}")


def cmd_tree(entries, order, args):
    children = {eid: [] for eid in order}
    roots = []
    for eid in order:
        deps = [d for d in entries[eid].deps if d in entries]
        if not deps:
            roots.append(eid)
        for d in deps:
            children[d].append(eid)

    printed = set()

    def walk(eid, depth):
        if args.area and entries[eid].area != args.area:
            return
        e = entries[eid]
        eff = effective_status(e, entries)
        mark = " (seen)" if eid in printed else ""
        print(f"{'  ' * depth}{emoji(eff)} {eid}{mark}")
        if eid in printed:
            return
        printed.add(eid)
        for c in children[eid]:
            walk(c, depth + 1)

    for r in roots:
        walk(r, 0)


def cmd_stats(entries, order, args):
    counts = {}
    for eid in order:
        eff = effective_status(entries[eid], entries)
        counts[eff] = counts.get(eff, 0) + 1
    total = len(order)
    print(f"{total} step(s) tracked:")
    for st in STATUS_EMOJI:
        if counts.get(st):
            print(f"  {emoji(st)} {st:<14} {counts[st]}")


def cmd_check(entries, order, args):
    problems = 0
    for eid in order:
        e = entries[eid]
        if e.status not in VALID_STATUS:
            print(f"‼ {eid}: invalid status '{e.status}'", file=sys.stderr)
            problems += 1
        for d in e.deps:
            if d not in entries:
                print(f"‼ {eid}: unknown dependency '{d}'", file=sys.stderr)
                problems += 1
        if e.status == "re-verified" and not e.evidence:
            print(f"‼ {eid}: re-verified but no evidence cited (RE must name ground truth)",
                  file=sys.stderr)
            problems += 1
    # cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {eid: WHITE for eid in order}

    def dfs(eid, stack):
        color[eid] = GRAY
        for d in entries[eid].deps:
            if d not in entries:
                continue
            if color[d] == GRAY:
                print(f"‼ dependency cycle: {' -> '.join(stack + [d])}", file=sys.stderr)
                return True
            if color[d] == WHITE and dfs(d, stack + [d]):
                return True
        color[eid] = BLACK
        return False

    for eid in order:
        if color[eid] == WHITE and dfs(eid, [eid]):
            problems += 1
    hacks = sum(1 for i in order if entries[i].status == "hack")
    if hacks:
        print(f"⛔ {hacks} hack(s) present — debt, run `re_frontier.py hacks` (not a check failure, "
              f"but must be burned down).", file=sys.stderr)
    if problems:
        print(f"\n{problems} problem(s) found.", file=sys.stderr)
        return 1
    if not DOC.exists:
        print(f"{DOC.path} does not exist; set $RE_FRONTIER_ROADMAP or run `scaffold`",
              file=sys.stderr)
        return 1
    if not order:
        print(f"{DOC.path} has {len(DOC.lines)} lines but no entries parsed; run `scaffold` or fix "
              f"the entry format", file=sys.stderr)
        return 1
    print(f"re-frontier OK: {len(order)} entr(ies) parsed from {DOC.path} "
          f"({len(DOC.lines)} lines) — no unknown deps, no cycles, every re-verified step "
          f"cites evidence.")
    return 0


def cmd_scaffold(entries, order, args):
    """Bootstrap an empty roadmap at $RE_FRONTIER_ROADMAP (or docs/re-frontier.md)."""
    if os.path.exists(ROADMAP):
        print(f"{ROADMAP} already exists — not overwriting.", file=sys.stderr)
        return 1
    d = os.path.dirname(ROADMAP)
    if d:
        os.makedirs(d, exist_ok=True)
    starter = Entry("area.first-step", "Describe the first RE step in this chain", args.area or "core")
    starter.gap = "Fill in real steps; add deps to encode the RE dependency order."
    with open(ROADMAP, "w", encoding="utf-8") as fh:
        fh.write(HEADER)
        fh.write(f"\n## {starter.area}\n\n")
        fh.write(starter.serialize() + "\n")
    print(f"scaffolded {ROADMAP} — edit it, then `re_frontier.py check`.")
    return 0


def cmd_add(entries, order, args):
    if args.id in entries:
        print(f"entry '{args.id}' already exists (use `set`)", file=sys.stderr)
        return 1
    if args.status not in VALID_STATUS:
        print(f"invalid status '{args.status}'", file=sys.stderr)
        return 1
    if not DOC.exists:
        print(f"{DOC.path} does not exist — refusing to create it from `add` "
              f"(run `scaffold`, or set $RE_FRONTIER_ROADMAP to the real roadmap).",
              file=sys.stderr)
        return 1
    e = Entry(args.id, args.title, args.area)
    e.status = args.status
    e.deps = [d.strip() for d in (args.deps or "").split(",") if d.strip()]
    e.evidence = args.evidence or ""
    e.where = args.where or ""
    e.gap = args.gap or ""
    e.notes = args.notes or ""
    lines, at = _area_insert_point(list(DOC.lines), e.area)
    block = [""] + e.serialize().split("\n")
    commit(lines[:at] + block + lines[at:], [], f"added {e.id}")
    return 0


def cmd_set(entries, order, args):
    e = entries.get(args.id)
    if not e:
        print(f"no such entry: {args.id}", file=sys.stderr)
        return 1
    updates, new_title, new_area = [], None, None
    for kv in args.assignments:
        if "=" not in kv:
            print(f"bad assignment '{kv}' (want field=value)", file=sys.stderr)
            return 1
        key, val = kv.split("=", 1)
        key = key.strip()
        if key == "status":
            if val not in VALID_STATUS:
                print(f"invalid status '{val}'", file=sys.stderr)
                return 1
            updates.append((key, val))
        elif key in ("deps", "evidence", "where", "gap", "notes"):
            updates.append((key, val))
        elif key == "title":
            new_title = val
        elif key == "area":
            new_area = val
        else:
            print(f"unknown field '{key}'", file=sys.stderr)
            return 1

    lines, drops = apply_field_edits(DOC.lines, e, updates)
    head_text = lines[e.head_line]
    if new_title is not None:
        lines, d2 = rewrite_heading(lines, e, e.id, new_title)
        drops += d2
        head_text = lines[e.head_line]
    if new_area is not None and new_area != e.area:
        lines = move_entry_to_area(lines, head_text, new_area)
    commit(lines, drops, f"updated {e.id}")
    return 0


def main():
    p = argparse.ArgumentParser(description="RE-frontier progress tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list"); sp.add_argument("--area"); sp.add_argument("--status")
    sp = sub.add_parser("show"); sp.add_argument("id")
    sp = sub.add_parser("next"); sp.add_argument("--area")
    sub.add_parser("hacks")
    sub.add_parser("blocked")
    sp = sub.add_parser("tree"); sp.add_argument("--area")
    sub.add_parser("stats")
    sub.add_parser("check")
    sp = sub.add_parser("scaffold"); sp.add_argument("--area")
    sp = sub.add_parser("add")
    sp.add_argument("id"); sp.add_argument("--title", required=True)
    sp.add_argument("--area", required=True); sp.add_argument("--status", default="todo")
    sp.add_argument("--deps"); sp.add_argument("--evidence"); sp.add_argument("--where")
    sp.add_argument("--gap"); sp.add_argument("--notes")
    sp = sub.add_parser("set"); sp.add_argument("id")
    sp.add_argument("assignments", nargs="+")

    args = p.parse_args()
    entries, order = load()
    fn = {
        "list": cmd_list, "show": cmd_show, "next": cmd_next, "hacks": cmd_hacks,
        "blocked": cmd_blocked, "tree": cmd_tree, "stats": cmd_stats, "check": cmd_check,
        "scaffold": cmd_scaffold, "add": cmd_add, "set": cmd_set,
    }[args.cmd]
    sys.exit(fn(entries, order, args) or 0)


if __name__ == "__main__":
    main()
