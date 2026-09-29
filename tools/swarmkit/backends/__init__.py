"""Registry of worker backends by CLI name."""

from __future__ import annotations

from .base import Backend
from .opencode import OpencodeBackend
from .pi import PiBackend

BACKENDS: dict[str, Backend] = {
    OpencodeBackend.name: OpencodeBackend(),
    PiBackend.name: PiBackend(),
}
DEFAULT_BACKEND = OpencodeBackend.name

__all__ = ["BACKENDS", "DEFAULT_BACKEND", "Backend"]
