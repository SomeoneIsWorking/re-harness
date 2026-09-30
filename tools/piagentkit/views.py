"""Render agent state as text for a person reading a terminal.

Every function here is pure: it takes data the other modules collected and
returns lines. Nothing here reads a file, talks to pi, or keeps state, so the
wording of a status block can be checked without an agent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from . import transcript as tr
from .transcript import Summary, ToolCallRecord

RESULT_LINES = 3
TEXT_LINES = 3
LAST_TEXT_CHARS = 600
STAGE = "{label:<9} {value}"


def elapsed_text(seconds: float) -> str:
    """A compact duration: ``45s``, ``3m12s``, ``1h04m``."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def compact_text(text: str, limit: int) -> str:
    """Collapse to one bounded block: no more than ``limit`` characters."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def status_block(
    *,
    name: str,
    alive: bool,
    supervisor_pid: int | None,
    pi_pid: int | None,
    cwd: str,
    model: str | None,
    streaming: bool | None,
    summary: Summary,
    elapsed: float,
    state_data: dict[str, Any] | None,
    stats: dict[str, Any] | None,
    exit_code: int | None,
    error: str | None,
    stderr_lines: Sequence[str],
) -> list[str]:
    """One compact block: what the agent is, what it is doing, what it produced."""
    lines = [f"agent {name}"]
    if alive:
        activity = "streaming" if streaming else "idle"
        if streaming is None:
            activity = "unknown (get_state unavailable)"
        lines.append(
            STAGE.format(label="state", value=f"alive  supervisor {supervisor_pid}  pi {pi_pid}")
        )
        lines.append(STAGE.format(label="activity", value=f"{activity}"))
    else:
        detail = f"dead  exit {exit_code}" if exit_code is not None else "dead"
        if error:
            detail += f"  {error}"
        lines.append(STAGE.format(label="state", value=detail))
    lines.append(STAGE.format(label="cwd", value=cwd))
    if state_data and isinstance(state_data.get("model"), dict):
        model_name = str(state_data["model"].get("id") or model)
    else:
        model_name = model or "?"
    lines.append(STAGE.format(label="model", value=model_name))
    lines.append(
        STAGE.format(
            label="run",
            value=f"{summary.runs} run(s), {summary.turns} turn(s), "
            f"{'settled' if summary.settled else 'not settled yet'}",
        )
    )
    tool = summary.last_tool_call
    if tool is not None:
        marker = "current" if not tool.finished else "last"
        lines.append(
            STAGE.format(label="tool", value=f"{tool.name} ({marker})  {tool.argument_line()}")
        )
    else:
        lines.append(STAGE.format(label="tool", value="none yet"))
    files = summary.edited_files
    lines.append(
        STAGE.format(label="files", value=", ".join(files) if files else "none edited")
    )
    lines.append(STAGE.format(label="elapsed", value=elapsed_text(elapsed)))
    usage = _usage_line(stats, summary.usage)
    if usage:
        lines.append(STAGE.format(label="usage", value=usage))
    if summary.malformed:
        lines.append(STAGE.format(label="framing", value=f"{summary.malformed} malformed record(s)"))
    if summary.errors:
        lines.append(STAGE.format(label="errors", value=summary.errors[-1]))
    text = summary.streaming_text or summary.last_assistant_text
    lines.append(STAGE.format(label="last", value=compact_text(text, LAST_TEXT_CHARS) or "(no assistant text yet)"))
    for line in stderr_lines:
        lines.append(STAGE.format(label="stderr", value=line))
    return lines


def _usage_line(stats: dict[str, Any] | None, event_usage: dict[str, Any] | None) -> str:
    if stats:
        tokens = stats.get("tokens") or {}
        context = stats.get("contextUsage") or {}
        parts: list[str] = []
        if context.get("percent") is not None:
            parts.append(
                f"context {round(float(context['percent']), 1)}% "
                f"of {context.get('contextWindow', '?')}"
            )
        elif context.get("tokens") is not None:
            parts.append(f"context {context.get('tokens')} tokens")
        if isinstance(tokens, dict) and tokens:
            parts.append(
                f"tokens in {tokens.get('input', 0)} / out {tokens.get('output', 0)}"
            )
        if stats.get("cost") is not None:
            parts.append(f"cost ${stats['cost']:.4f}")
        if parts:
            return ", ".join(parts)
    if event_usage:
        total = event_usage.get("totalTokens")
        output = event_usage.get("output")
        if total is not None:
            return f"last response {total} tokens (out {output or 0})"
    return ""


def tail_lines(events: Sequence[tuple[bytes, Any | None]], limit: int) -> list[str]:
    """A human-readable transcript of the last ``limit`` events."""
    lines: list[str] = []
    for raw, parsed in events:
        lines.extend(_event_line(raw, parsed))
    return lines[-limit:] if limit > 0 else lines


def _event_line(raw: bytes, parsed: Any | None) -> list[str]:
    if not isinstance(parsed, dict):
        return [f"!  malformed record: {_preview(raw)}"]
    kind = parsed.get("type", "?")
    if kind == "response":
        return []  # command traffic, not the conversation
    if kind in ("agent_start", "agent_settled", "turn_start"):
        return [f"·  {kind}"]
    if kind == "agent_end":
        retry = " (will retry)" if parsed.get("willRetry") else ""
        return [f"·  agent_end{retry}"]
    if kind == "turn_end":
        return [f"·  turn_end"]
    if kind == "message_start":
        message = parsed.get("message")
        if isinstance(message, dict) and message.get("role") == "user":
            return [f">  user: {_preview(tr.text_of(tr.content_of(message)))}"]
        return []
    if kind == "message_end":
        message = parsed.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return []
        text = tr.text_of(tr.content_of(message))
        if message.get("stopReason") == "error" or message.get("errorMessage"):
            return [f"!  assistant error: {message.get('errorMessage', 'unknown')}"]
        return [f"   {_preview(line)}" for line in _first_lines(text, TEXT_LINES)]
    if kind == "message_update":
        update = parsed.get("assistantMessageEvent")
        if isinstance(update, dict) and update.get("type") == "text_delta":
            return []  # the completed message_end carries the authoritative text
        if isinstance(update, dict) and update.get("type") == "error":
            return [f"!  provider stream error: {update.get('reason', '?')} {update.get('error', '')}".rstrip()]
        return []
    if kind == "tool_execution_start":
        call = ToolCallRecord(
            name=str(parsed.get("toolName", "?")),
            arguments=tr.as_dict(parsed.get("args")),
        )
        return [f"   tool {call.name}  {call.argument_line()}"]
    if kind == "tool_execution_end":
        result = tr.text_of(tr.content_of(parsed.get("result")))
        marker = "!" if parsed.get("isError") else "="
        return [f"   {marker} {str(parsed.get('toolName', '?'))} -> {line}" for line in _first_lines(result, RESULT_LINES)]
    if kind.startswith("compaction") or kind.startswith("summarization_retry") or kind == "auto_retry_start" or kind == "auto_retry_end":
        return [f"!  {kind}: {_preview(tr.text_of(tr.content_of(parsed)) or _compact(parsed))}"]
    if kind == "extension_error":
        return [f"!  extension_error {parsed.get('extensionPath', '?')}: {parsed.get('error', '?')}"]
    if kind == "queue_update":
        steering = parsed.get("steering") or []
        follow_up = parsed.get("followUp") or []
        if steering or follow_up:
            return [f"·  queued: {len(steering)} steering, {len(follow_up)} follow-up"]
        return []
    if kind == "extension_ui_request":
        detail = parsed.get("message") or parsed.get("statusText") or parsed.get("method", "?")
        return [f"·  ext {parsed.get('method', '?')}: {_preview(detail)}"]
    if kind == "extension_ui_response":
        return [f"·  ext answered {parsed.get('id', '?')}"]
    return [f"·  {kind}"]


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _first_lines(text: str, count: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ["(empty)"]
    return lines[:count]


def _preview(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class AgentRow:
    """One line of ``piagent.py list``."""

    name: str
    alive: bool
    activity: str
    cwd: str
    age: float

    def render(self) -> str:
        state = "alive" if self.alive else "dead"
        return (
            f"{self.name:<20} {state:<5} {self.activity:<9} "
            f"{elapsed_text(self.age):<7} {self.cwd}"
        )


def list_header() -> str:
    return f"{'NAME':<20} {'ALIVE':<5} {'ACTIVITY':<9} {'AGE':<7} CWD"
