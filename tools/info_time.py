"""Portable timestamps for project-information evidence baselines."""

from __future__ import annotations

import datetime


UTC = datetime.timezone.utc


def now_stamp() -> str:
    """Return a second-precision, timezone-aware UTC timestamp."""
    return datetime.datetime.now(UTC).replace(microsecond=0).isoformat(sep=" ")


def timestamp_epoch(value: str) -> int | None:
    """Parse current or legacy baselines without consulting the host timezone."""
    for candidate in (value, value[:10]):
        try:
            parsed = datetime.datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            # Legacy claim timestamps carried no offset. UTC is the only portable
            # interpretation; host-local conversion made CI disagree with operators.
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    return None
