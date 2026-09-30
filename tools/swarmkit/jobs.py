"""Parse and validate a JSONL jobs file into immutable ``Job`` values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
DEFAULT_GATE_TIMEOUT_SECONDS = 3600.0
KNOWN_FIELDS = {
    "id",
    "repo",
    "prompt",
    "files",
    "read_only",
    "gate",
    "heavy_gate",
    "mem_mib",
    "timeout",
    "gate_timeout",
}


class JobFileError(ValueError):
    """The jobs file is malformed; the message names the line and field."""


@dataclass(frozen=True)
class Job:
    """One bounded unit of work: a prompt for the worker and the argv that judges it."""

    id: str
    repo: Path
    prompt: str
    gate: tuple[str, ...]
    timeout: float
    files: tuple[str, ...] = ()
    # Absolute directories outside the worktree the worker may read but not edit, e.g.
    # a gitignored generated tree or an uninitialised submodule of the main checkout.
    read_only: tuple[Path, ...] = ()
    heavy_gate: bool = False
    # Peak this job's heavy gate may grow into, overriding the build default. A gate
    # that is not heavy has no admission of its own, so it would mean nothing there.
    mem_mib: int | None = None
    gate_timeout: float = DEFAULT_GATE_TIMEOUT_SECONDS


def load_jobs(path: Path) -> list[Job]:
    """Read every non-blank line of ``path``; relative ``repo`` paths resolve against its directory."""
    jobs: list[Job] = []
    seen: set[str] = set()
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        where = f"{path}:{number}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise JobFileError(f"{where}: not JSON: {error}") from error
        job = _parse(record, where, path.parent)
        if job.id in seen:
            raise JobFileError(f"{where}: duplicate job id {job.id!r}")
        seen.add(job.id)
        jobs.append(job)
    if not jobs:
        raise JobFileError(f"{path}: no jobs")
    return jobs


def _parse(record: object, where: str, base: Path) -> Job:
    if not isinstance(record, dict):
        raise JobFileError(f"{where}: a job must be a JSON object")
    unknown = set(record) - KNOWN_FIELDS
    if unknown:
        raise JobFileError(f"{where}: unknown field(s) {sorted(unknown)}")
    job_id = _required(record, "id", str, where)
    if not JOB_ID.match(job_id):
        raise JobFileError(f"{where}: id {job_id!r} must match {JOB_ID.pattern}")
    prompt = _required(record, "prompt", str, where)
    if not prompt.strip():
        raise JobFileError(f"{where}: prompt is empty")
    gate = record.get("gate")
    if (
        not isinstance(gate, list)
        or not gate
        or not all(isinstance(a, str) and a for a in gate)
    ):
        raise JobFileError(f"{where}: gate must be a non-empty argv list of strings")
    files = record.get("files", [])
    if not isinstance(files, list) or not all(isinstance(f, str) and f for f in files):
        raise JobFileError(f"{where}: files must be a list of paths")
    read_only = record.get("read_only", [])
    if not isinstance(read_only, list) or not all(
        isinstance(r, str) and r for r in read_only
    ):
        raise JobFileError(f"{where}: read_only must be a list of paths")
    heavy = record.get("heavy_gate", False)
    if not isinstance(heavy, bool):
        raise JobFileError(f"{where}: heavy_gate must be true or false")
    mem_mib = _positive_int(record, "mem_mib", where)
    if mem_mib is not None and not heavy:
        raise JobFileError(
            f"{where}: mem_mib reserves memory for a heavy gate; "
            "set heavy_gate true or drop it"
        )
    repo = (base / Path(_required(record, "repo", str, where)).expanduser()).resolve()
    readable = tuple((repo / r).resolve() for r in read_only)
    missing = [str(r) for r in readable if not r.is_dir()]
    if missing:
        raise JobFileError(f"{where}: read_only directories do not exist: {missing}")
    return Job(
        id=job_id,
        repo=repo,
        prompt=prompt,
        gate=tuple(gate),
        timeout=_seconds(record, "timeout", where, None),
        files=tuple(files),
        read_only=readable,
        heavy_gate=heavy,
        mem_mib=mem_mib,
        gate_timeout=_seconds(
            record, "gate_timeout", where, DEFAULT_GATE_TIMEOUT_SECONDS
        ),
    )


def _required(record: dict, name: str, kind: type, where: str):
    value = record.get(name)
    if not isinstance(value, kind):
        raise JobFileError(f"{where}: field {name!r} is required ({kind.__name__})")
    return value


def _seconds(record: dict, name: str, where: str, default: float | None) -> float:
    value = record.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise JobFileError(f"{where}: {name!r} must be a positive number of seconds")
    return float(value)


def _positive_int(record: dict, name: str, where: str) -> int | None:
    """An optional whole number of MiB; anything else is a malformed jobs file."""
    if name not in record:
        return None
    value = record[name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JobFileError(f"{where}: {name!r} must be a positive whole number of MiB")
    return value
