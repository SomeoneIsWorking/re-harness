"""The client half of the supervisor's UNIX control socket.

A client sends exactly one RPC command record per connection and reads the
matching ``response``. It never holds pi's stdin, so two operators (or an
operator and a ``--follow``) cannot interleave half-written commands.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from .config import RPC_TIMEOUT_SECONDS
from .framing import decode_record, encode_record, iter_records


class ControlError(RuntimeError):
    """The control socket could not be reached or answered unusably."""


class ControlLink:
    """Send one RPC command to the supervisor and return pi's response."""

    def __init__(self, socket_path: Path, timeout: float = RPC_TIMEOUT_SECONDS) -> None:
        self._path = socket_path
        self._timeout = timeout

    def request(self, command: str, **fields: Any) -> dict[str, Any]:
        """Run one RPC command; raises ``ControlError`` on any transport failure."""
        connection = self._connect()
        try:
            connection.sendall(encode_record({"type": command, **fields}))
            connection.settimeout(self._timeout)
            for record in iter_records(lambda size: connection.recv(size)):
                parsed = decode_record(record)
                if isinstance(parsed, dict):
                    return parsed
            raise ControlError(f"{self._path}: supervisor closed without a response")
        except (OSError, ValueError) as error:
            raise ControlError(f"{self._path}: {error}") from error
        finally:
            connection.close()

    def _connect(self) -> socket.socket:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self._timeout)
        try:
            connection.connect(str(self._path))
        except OSError as error:
            connection.close()
            raise ControlError(f"{self._path}: {error}") from error
        return connection

    def probe(self) -> bool:
        """True when the supervisor answers on the socket at all."""
        try:
            self.request("get_state")
        except ControlError:
            return False
        return True


def data_of(response: dict[str, Any]) -> dict[str, Any]:
    """The ``data`` object of a successful response, or an empty mapping."""
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def error_of(response: dict[str, Any]) -> str:
    """pi's error string for a failed response, or a description of the shape."""
    if response.get("success") is True:
        return ""
    error = response.get("error")
    return str(error) if error else f"unexpected response: {sorted(response)}"
