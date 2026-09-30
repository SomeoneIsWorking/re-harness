"""Read an agent's ``events.jsonl`` and answer questions about the run.

The event stream is the durable record; this module is the only place that
interprets it. ``summarize`` answers the status/tail questions, ``read_events``
yields records, and both report malformed records instead of skipping them
silently.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Tools that change a file on disk; their argument names differ, so both the
# current ``path`` and the historical ``filePath`` are accepted.
EDIT_TOOLS = ("edit", "write", "multiedit", "notebookedit", "apply_patch")
FILE_ARGUMENTS = ("path", "file_path", "filePath", "target_file", "notebook_path")
MAX_ARGUMENT_CHARS = 120

@dataclass
class ToolCallRecord:
    """One tool call, joined from its execution start and end."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    result: str = ""
    is_error: bool = False
    finished: bool = False

    @property
    def edited_file(self) -> str | None:
        if self.name not in EDIT_TOOLS:
            return None
        for key in FILE_ARGUMENTS:
            value = self.arguments.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def argument_line(self) -> str:
        """A one-line summary of the arguments, for a human reading a transcript."""
        for key in FILE_ARGUMENTS:
            value = self.arguments.get(key)
            if isinstance(value, str) and value:
                return f"{key}={value}"
        text = json.dumps(self.arguments, ensure_ascii=False, sort_keys=True)
        return text[:MAX_ARGUMENT_CHARS]


@dataclass
class Summary:
    """Everything status and tail need, computed once from the record stream."""

    records: int = 0
    malformed: int = 0
    runs: int = 0
    turns: int = 0
    settled: bool = False
    open_run: bool = False
    last_assistant_text: str = ""
    streaming_text: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    last_event: str = ""

    @property
    def current_tool(self) -> ToolCallRecord | None:
        for call in reversed(self.tool_calls):
            if not call.finished:
                return call
        return None

    @property
    def last_tool(self) -> ToolCallRecord | None:
        return self.tool_calls[-1] if self.tool_calls else None

    @property
    def last_tool_call(self) -> ToolCallRecord | None:
        return self.current_tool or self.last_tool

    @property
    def edited_files(self) -> list[str]:
        seen: list[str] = []
        for call in self.tool_calls:
            path = call.edited_file
            if path and path not in seen:
                seen.append(path)
        return seen

    @property
    def errors(self) -> list[str]:
        return [note for note in self.notices if note.startswith("error")]


def read_events(path: Path) -> list[tuple[bytes, Any | None]]:
    """Load every record from an event log; a missing log is an empty one."""
    if not path.is_file():
        return []
    raw = path.read_bytes()
    records: list[tuple[bytes, Any | None]] = []
    start = 0
    while True:
        end = raw.find(b"\n", start)
        if end < 0:
            tail = raw[start:]
            if tail:
                records.append(_parse(tail))
            break
        records.append(_parse(raw[start:end]))
        start = end + 1
    return records


def _parse(raw: bytes) -> tuple[bytes, Any | None]:
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return raw, None


def iter_parsed(path: Path) -> Iterator[Any | None]:
    for _, parsed in read_events(path):
        yield parsed


def summarize(records: Sequence[Any | None]) -> Summary:
    """Fold the event stream into a ``Summary``.

    A ``message_end`` assistant message is authoritative for its text; while a
    message is still open the accumulated ``text_delta``s stand in for it.
    """
    summary = Summary()
    open_text: list[str] = []
    started_run = False
    for parsed in records:
        summary.records += 1
        if not isinstance(parsed, dict):
            summary.malformed += 1
            summary.notices.append("error malformed record dropped from the stream")
            continue
        kind = parsed.get("type", "")
        summary.last_event = str(kind)
        if kind == "agent_start":
            summary.runs += 1
            started_run = True
            open_text = []
        elif kind == "agent_end":
            started_run = False
        elif kind == "agent_settled":
            summary.settled = True
            started_run = False
        elif kind == "turn_end":
            summary.turns += 1
        elif kind == "message_start" and _role(parsed) == "assistant":
            open_text = []
        elif kind == "message_update":
            _apply_update(summary, parsed, open_text)
        elif kind == "message_end" and _role(parsed) == "assistant":
            text = text_of(content_of(parsed.get("message")))
            if text:
                summary.last_assistant_text = text
                summary.streaming_text = text
            open_text = []
        elif kind == "tool_execution_start":
            _record_tool_call(
                summary,
                {
                    "id": parsed.get("toolCallId", ""),
                    "name": parsed.get("toolName", "?"),
                    "arguments": parsed.get("args"),
                },
            )
        elif kind == "tool_execution_end":
            _finish_tool(summary, parsed)
        elif kind in ("compaction_start", "compaction_end"):
            summary.notices.append(f"compaction {kind.split('_')[1]} ({parsed.get('reason', '?')})")
        elif kind in ("auto_retry_start", "auto_retry_end"):
            summary.notices.append(
                f"retry {kind.split('_')[-1]} attempt {parsed.get('attempt', '?')}"
            )
        elif kind.startswith("summarization_retry"):
            summary.notices.append(f"retry summarization {kind.split('_')[-1]}")
        elif kind == "extension_error":
            summary.notices.append(
                f"error extension {parsed.get('extensionPath', '?')}: {parsed.get('error', '?')}"
            )
    summary.open_run = started_run
    if summary.open_run and open_text:
        summary.streaming_text = "".join(open_text)
    return summary


def _apply_update(summary: Summary, parsed: dict[str, Any], open_text: list[str]) -> None:
    usage = parsed.get("usage")
    if isinstance(usage, dict) and usage:
        summary.usage = usage
    update = parsed.get("assistantMessageEvent")
    if not isinstance(update, dict):
        return
    kind = update.get("type")
    if kind == "text_delta" and isinstance(update.get("delta"), str):
        open_text.append(update["delta"])
    elif kind == "toolcall_end":
        call = update.get("toolCall")
        if isinstance(call, dict):
            _record_tool_call(summary, call)
    elif kind == "error":
        summary.notices.append(
            f"error provider stream: {update.get('reason', '?')} {update.get('error', '')}".strip()
        )


def _record_tool_call(summary: Summary, call: dict[str, Any]) -> None:
    """Remember a call the model asked for.

    The same call arrives twice: once as ``toolcall_end`` while the message is
    still streaming, and again as ``tool_execution_start`` when it runs. Keeping
    one record per id is what lets ``current_tool`` mean "started, not finished".
    """
    identifier = str(call.get("id", ""))
    existing = next((item for item in summary.tool_calls if item.call_id == identifier), None)
    if existing is not None:
        existing.arguments = as_dict(call.get("arguments")) or existing.arguments
        return
    summary.tool_calls.append(
        ToolCallRecord(
            name=str(call.get("name", "?")),
            arguments=as_dict(call.get("arguments")),
            call_id=identifier,
        )
    )


def _finish_tool(summary: Summary, parsed: dict[str, Any]) -> None:
    call_id = str(parsed.get("toolCallId", ""))
    name = str(parsed.get("toolName", ""))
    call = next(
        (item for item in reversed(summary.tool_calls) if item.call_id == call_id),
        None,
    )
    if call is None:
        call = ToolCallRecord(name=name or "?", call_id=call_id)
        summary.tool_calls.append(call)
    call.finished = True
    call.is_error = bool(parsed.get("isError"))
    call.result = text_of(content_of(parsed.get("result")))


def _role(parsed: dict[str, Any]) -> str:
    message = parsed.get("message")
    return str(message.get("role", "")) if isinstance(message, dict) else ""


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def content_of(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content")
    return None


def text_of(content: Any) -> str:
    """Flatten a message or tool-result content value into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(part for part in parts if part)
