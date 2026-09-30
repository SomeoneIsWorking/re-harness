"""The one reader of the kernel's process and memory state under ``/proc``.

Everything the swarm knows about memory and about process ownership comes
through here: ``MemAvailable``, the resident size of a process group, whether a
process group is stopped, and which processes are descendants of another one.
Other modules receive these as callables so a test can inject a fixed answer.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Callable, Iterable
from pathlib import Path

MIB = 1024 * 1024
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
PROC = Path("/proc")
# Fields of /proc/<pid>/stat after the comm field: state, ppid, pgrp, ...
STATE_INDEX = 0
PPID_INDEX = 1
PGRP_INDEX = 2
STOPPED_STATES = frozenset({"T", "t"})


def read_mem_available() -> int:
    """``MemAvailable`` from ``/proc/meminfo`` in bytes."""
    with open(PROC / "meminfo", encoding="ascii") as meminfo:
        for line in meminfo:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo has no MemAvailable line")


def read_group_rss(groups: Iterable[int]) -> dict[int, int]:
    """Resident bytes per process group in ``groups``, from one pass over ``/proc``."""
    wanted = set(groups)
    total: dict[int, int] = {group: 0 for group in wanted}
    if not wanted:
        return total
    for pid in _numeric_entries():
        group = _process_group(pid)
        if group in wanted:
            total[group] += _resident_bytes(pid)
    return total


def descendants(pid: int) -> list[int]:
    """Every process whose parent chain reaches ``pid``, from one pass over ``/proc``.

    The parent graph, not the process group: a descendant that started a session
    of its own -- a ``setsid`` daemon, a Gradle or MSBuild node -- is still a
    descendant, and a group kill aimed at the caller never reaches it.
    """
    children: dict[int, list[int]] = {}
    for entry in _numeric_entries():
        parent = _parent_pid(entry)
        if parent is not None:
            children.setdefault(parent, []).append(int(entry))
    found: list[int] = []
    pending = [pid]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.append(child)
                pending.append(child)
    return found


def group_stopped(group: int) -> bool:
    """True when the leader of ``group`` is stopped, so the group makes no progress."""
    return _state(group) in STOPPED_STATES


def group_alive(group: int) -> bool:
    """True when any process remains in ``group``; the kernel's own answer."""
    return _alive(os.killpg, group)


def process_alive(pid: int) -> bool:
    """True when ``pid`` still names a process, whatever group it is in."""
    return _alive(os.kill, pid)


def process_running(pid: int) -> bool:
    """True when ``pid`` is alive and not a zombie waiting to be reaped."""
    return process_alive(pid) and _state(pid) != "Z"


def _alive(sender: Callable[[int, int], None], target: int) -> bool:
    try:
        sender(target, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        return error.errno != errno.ESRCH
    return True


def _numeric_entries() -> list[str]:
    try:
        names = os.listdir(PROC)
    except FileNotFoundError:
        return []
    return [name for name in names if name.isdigit()]


def _stat_fields(pid: str | int) -> list[str] | None:
    """The space-separated fields after ``comm``; None when the process is gone."""
    try:
        raw = (PROC / str(pid) / "stat").read_text(encoding="ascii", errors="replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    return raw.rsplit(")", 1)[-1].split()


def _parent_pid(pid: str) -> int | None:
    fields = _stat_fields(pid)
    if fields is None or len(fields) <= PPID_INDEX:
        return None
    return int(fields[PPID_INDEX])


def _process_group(pid: str) -> int | None:
    fields = _stat_fields(pid)
    if fields is None or len(fields) <= PGRP_INDEX:
        return None
    return int(fields[PGRP_INDEX])


def _state(pid: str | int) -> str:
    fields = _stat_fields(pid)
    if not fields or len(fields) <= STATE_INDEX:
        return ""
    return fields[STATE_INDEX]


def _resident_bytes(pid: str) -> int:
    try:
        pages = (PROC / pid / "statm").read_text(encoding="ascii").split()[1]
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
        return 0
    return int(pages) * PAGE_SIZE
