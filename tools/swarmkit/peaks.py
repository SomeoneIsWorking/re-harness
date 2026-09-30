"""Learned memory peaks: reserve what a heavy command was measured to use, not a guess.

Every build reserved the kind's fixed 3072 MiB. On 2026-09-30 two psx builds
held 6 GiB of reservation while using 198 and 317 MiB, and four game runs waited
behind them with 7 GiB free. A command's peak is now sampled while it runs and
kept per command; the next run of the same command reserves that peak with
headroom. A command never measured gets the kind's default, and the kept value
is the highest ever seen, so an incremental rebuild never talks a full build's
reservation down. The pressure watcher remains the backstop for a peak that
grows past what was learned.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .procs import MIB, descendants, read_tree_rss

PEAKS_FILE = "heavy-peaks.json"
# Headroom over the highest peak seen, and the least a learned reservation may be.
HEADROOM = 1.25
MINIMUM_MIB = 256
SAMPLE_SECONDS = 0.5


def command_key(kind: str, root: Path, argv: Sequence[str]) -> str:
    """One command, identified by its kind, the checkout it runs in, and its argv."""
    text = json.dumps([kind, str(root), list(argv)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PeakHistory:
    """The highest peak measured per command, shared by every heavy.py on the machine."""

    def __init__(self, lock_dir: Path) -> None:
        self.path = lock_dir / PEAKS_FILE
        self.lock_path = lock_dir / (PEAKS_FILE + ".lock")

    def reservation(self, key: str, default_mib: int) -> int:
        """The MiB to reserve for ``key``: its learned peak with headroom, else ``default_mib``."""
        peak = self._read().get(key)
        if peak is None:
            return default_mib
        return max(MINIMUM_MIB, math.ceil(peak * HEADROOM))

    def record(self, key: str, peak_mib: int) -> None:
        """Keep ``peak_mib`` for ``key`` if it is the highest seen."""
        with self._locked():
            peaks = self._read()
            if peak_mib <= peaks.get(key, 0):
                return
            peaks[key] = peak_mib
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(peaks, indent=1) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)

    def _read(self) -> dict[str, int]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)


class PeakSampler:
    """The highest resident total of a process and its descendants while it runs."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> PeakSampler:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()

    @property
    def peak_mib(self) -> int:
        return math.ceil(self.peak_bytes / MIB)

    def _sample(self) -> None:
        while True:
            self.peak_bytes = max(
                self.peak_bytes, read_tree_rss([self.pid, *descendants(self.pid)])
            )
            if self._stop.wait(SAMPLE_SECONDS):
                return
