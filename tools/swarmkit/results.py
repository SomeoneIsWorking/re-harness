"""Per-job verdicts and their on-disk record (``<run>/<id>/result.json``)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

RESULT_FILE = "result.json"
PATCH_FILE = "patch.diff"
RUN_FILE = "run.json"


class Verdict(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WORKER_FAILED = "worker-failed"
    TIMEOUT = "timeout"


class Reason(str, Enum):
    """Why a job was not accepted: which check said no, or which phase ran out of time."""

    GATE_FAILED = "gate-failed"
    EMPTY_PATCH = "empty-patch"
    WORKER_EXIT = "worker-exit"
    SETUP = "setup"
    WORKER = "worker"
    GATE = "gate"


@dataclass
class JobResult:
    id: str
    repo: str
    base: str
    verdict: Verdict
    reason: Reason | None
    attempts: int
    gate: list[str]
    gate_returncode: int | None = None
    gate_tail: str = ""
    worker_returncode: int | None = None
    worker_tail: str = ""
    changed_files: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def __post_init__(self) -> None:
        # The single invariant the whole tool exists for: only the gate accepts.
        if self.verdict is Verdict.ACCEPTED and self.gate_returncode != 0:
            raise ValueError(
                f"{self.id}: accepted requires gate exit 0, got {self.gate_returncode}"
            )
        if (self.verdict is Verdict.ACCEPTED) != (self.reason is None):
            raise ValueError(
                f"{self.id}: verdict {self.verdict.value} with reason {self.reason}"
            )

    def write(self, job_dir: Path) -> None:
        record = asdict(self)
        record["verdict"] = self.verdict.value
        record["reason"] = self.reason.value if self.reason else None
        (job_dir / RESULT_FILE).write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def read(cls, job_dir: Path) -> JobResult:
        record = json.loads((job_dir / RESULT_FILE).read_text(encoding="utf-8"))
        record["verdict"] = Verdict(record["verdict"])
        record["reason"] = Reason(record["reason"]) if record["reason"] else None
        return cls(**record)
