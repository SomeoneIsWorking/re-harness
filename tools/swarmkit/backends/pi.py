"""``pi -p`` worker; pi reaches Space Bunny as ``opencode/space-bunny-free``."""

from __future__ import annotations

from collections.abc import Sequence


class PiBackend:
    name = "pi"

    def command(self, prompt: str, files: Sequence[str], model: str) -> list[str]:
        argv = ["pi", "-p", "--no-session", "--model", model, "--"]
        return argv + [f"@{attached}" for attached in files] + [prompt]
