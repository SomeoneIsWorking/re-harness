"""Line-atomic progress output shared by worker threads."""

from __future__ import annotations

import sys
import threading

_LOCK = threading.Lock()


def emit(line: str) -> None:
    with _LOCK:
        print(line, file=sys.stderr, flush=True)
