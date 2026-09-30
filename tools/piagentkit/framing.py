"""JSONL framing for pi's stdout, split on LF and nothing else.

``U+2028`` and ``U+2029`` are legal inside a JSON string. ``str.splitlines`` and
Node's ``readline`` treat them as record boundaries and would cut a record in
half, so every reader here works on bytes and splits only on ``b"\\n"``,
stripping an optional preceding carriage return.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

NEWLINE = b"\n"
READ_CHUNK = 1 << 16


def iter_records(
    read: Callable[[int], bytes], chunk_size: int = READ_CHUNK
) -> Iterator[bytes]:
    """Yield each LF-terminated record as bytes, without its terminator.

    A trailing record not terminated by LF is still yielded: a truncated stream
    must be visible to the caller rather than silently dropped.
    """
    pending = b""
    while True:
        chunk = read(chunk_size)
        if not chunk:
            break
        pending += chunk
        start = 0
        while True:
            end = pending.find(NEWLINE, start)
            if end < 0:
                break
            yield _strip_carriage_return(pending[start:end])
            start = end + 1
        pending = pending[start:]
    if pending:
        yield _strip_carriage_return(pending)


def _strip_carriage_return(record: bytes) -> bytes:
    return record[:-1] if record.endswith(b"\r") else record


def encode_record(value: Any) -> bytes:
    """Serialize one protocol record, LF-terminated, as UTF-8 bytes."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + NEWLINE
    )


def decode_record(record: bytes) -> Any:
    """Parse one record; raises ``ValueError`` when the stream is not JSON."""
    return json.loads(record.decode("utf-8"))


def read_records(stream: Any) -> Iterator[tuple[bytes, Any | None]]:
    """Yield ``(raw, parsed)`` for every record on a byte stream.

    ``parsed`` is ``None`` for a record that is not valid JSON, so the caller can
    report it instead of losing it.
    """
    reader = stream.read1 if hasattr(stream, "read1") else stream.read
    for raw in iter_records(reader):
        try:
            yield raw, decode_record(raw)
        except (ValueError, UnicodeDecodeError):
            yield raw, None
