#!/usr/bin/env python3
"""A stand-in for ``pi --mode rpc`` that speaks the real protocol.

Commands: prompt, steer, follow_up, abort, get_state, get_session_stats,
get_last_assistant_text. Each accepted message produces a scripted run (agent
start, user and assistant messages, an ``edit`` tool call, agent end, settled) and
any queued steer or follow-up is delivered as a further run.

Every response to prompt/steer/follow_up echoes the submitted text back, so a
caller that framed the stream wrongly shows it here.

    --slow SECONDS   pause between run steps, so steer can be tested
    --die-code N     exit N right after answering the first prompt
    --no-tool        skip the tool call, for a text-only run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

LOCK = threading.Lock()
STATE = {
    "streaming": False,
    "queued": [],  # list of [kind, text]
    "turns": 0,
    "last_text": "",
    "abort": False,
}
POLL = 0.05


def emit(record: dict) -> None:
    with LOCK:
        sys.stdout.buffer.write(
            json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        )
        sys.stdout.buffer.flush()


def usage() -> dict:
    return {
        "input": 1000,
        "output": 120,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 1120,
        "cost": {"input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0, "total": 0.0},
    }


def response(identifier, command, data=None, success=True, error=None):
    record = {"id": identifier, "type": "response", "command": command, "success": success}
    if data is not None:
        record["data"] = data
    if error is not None:
        record["error"] = error
    emit(record)


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def pause(seconds: float) -> bool:
    """Sleep in slices; True as soon as an abort arrives."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if STATE["abort"]:
            return True
        time.sleep(POLL)
    return STATE["abort"]


def run(message: str, options) -> None:
    """One scripted agent run, then whatever was queued behind it."""
    with LOCK:
        STATE["abort"] = False
    while True:
        with LOCK:
            aborted = STATE["abort"]
            if not aborted:
                STATE["streaming"] = True
        if aborted:
            finish("aborted", stop_reason="aborted", streaming=False)
            return
        emit({"type": "agent_start"})
        emit({"type": "message_start", "message": {"role": "user", "content": message, "timestamp": now_ms()}})
        emit({"type": "message_end", "message": {"role": "user", "content": message, "timestamp": now_ms()}})
        emit({"type": "turn_start"})
        if pause(options.slow):
            finish("aborted", stop_reason="aborted")
            return
        emit({"type": "message_start", "message": {"role": "assistant", "content": [], "stopReason": "pending"}})
        emit({
            "type": "message_update",
            "usage": usage(),
            "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "working"},
        })
        content = [text_block("working: noted")]
        if not options.no_tool:
            call_id = f"call-{STATE['turns'] + 1}"
            arguments = {"path": "notes.md", "edits": [{"oldText": "a", "newText": "b"}]}
            tool_call = {"type": "toolCall", "id": call_id, "name": "edit", "arguments": arguments}
            # pi announces the call on the message, then runs it, then ends it.
            emit({
                "type": "message_update",
                "usage": usage(),
                "assistantMessageEvent": {
                    "type": "toolcall_end", "contentIndex": 1, "toolCall": tool_call
                },
            })
            emit({"type": "tool_execution_start", "toolCallId": call_id, "toolName": "edit", "args": arguments})
            if pause(options.slow):
                finish("aborted", stop_reason="aborted")
                return
            emit({
                "type": "tool_execution_end",
                "toolCallId": call_id,
                "toolName": "edit",
                "result": {"content": [text_block("edited notes.md")], "details": {}},
                "isError": False,
            })
            content.append(tool_call)
        emit({
            "type": "message_end",
            "message": {"role": "assistant", "content": content, "stopReason": "toolUse", "usage": usage()},
        })
        emit({"type": "turn_end", "message": {"role": "assistant", "content": content}, "toolResults": []})
        finish("working: noted", stop_reason="toolUse")
        with LOCK:
            pending = STATE["queued"].pop(0) if STATE["queued"] else None
        if pending is None:
            return
        message = pending[1]


def finish(text: str, stop_reason: str, streaming: bool = False) -> None:
    """Close the run the way pi does: streaming off, then agent end and settled."""
    with LOCK:
        STATE["abort"] = False
        STATE["streaming"] = streaming
        STATE["turns"] += 1
        STATE["last_text"] = text
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled"})


def now_ms() -> int:
    return int(time.time() * 1000)


def handle(command: dict, options) -> None:
    identifier = command.get("id")
    kind = command.get("type")
    message = command.get("message", "")
    if kind == "prompt":
        with LOCK:
            if STATE["streaming"] and "streamingBehavior" not in command:
                response(identifier, "prompt", success=False, error="already streaming; set streamingBehavior")
                return
            behaviour = command.get("streamingBehavior")
            if STATE["streaming"] or behaviour in ("steer", "followUp"):
                STATE["queued"].append([behaviour or "followUp", message])
                response(identifier, "prompt", {"disposition": "queued", "echo": message})
                return
        response(identifier, "prompt", {"disposition": "started", "echo": message})
        if options.die_code:
            os._exit(options.die_code)
        threading.Thread(target=guarded, args=(message, options), daemon=True).start()
    elif kind in ("steer", "follow_up"):
        with LOCK:
            streaming = STATE["streaming"]
            if streaming:
                STATE["queued"].append([kind, message])
        response(identifier, kind, {"disposition": "queued", "echo": message})
        if not streaming:
            threading.Thread(target=guarded, args=(message, options), daemon=True).start()
    elif kind == "abort":
        STATE["abort"] = True
        response(identifier, "abort")
    elif kind == "get_state":
        response(identifier, "get_state", {
            "model": {"id": options.model, "provider": "fake", "name": "fake model"},
            "thinkingLevel": "off",
            "isStreaming": STATE["streaming"],
            "isCompacting": False,
            "sessionFile": os.path.join(os.getcwd(), "fake-session.jsonl"),
            "sessionId": "fake",
            "messageCount": STATE["turns"] + 1,
            "pendingMessageCount": len(STATE["queued"]),
        })
    elif kind == "get_session_stats":
        response(identifier, "get_session_stats", {
            "userMessages": 1,
            "assistantMessages": STATE["turns"],
            "toolCalls": STATE["turns"],
            "totalMessages": 2 * STATE["turns"] + 1,
            "tokens": usage(),
            "cost": 0.0,
            "contextUsage": {"tokens": 12000, "contextWindow": 200000, "percent": 6},
        })
    elif kind == "get_last_assistant_text":
        response(identifier, "get_last_assistant_text", {"text": STATE["last_text"]})
    else:
        response(identifier, str(kind), success=False, error=f"unknown command {kind!r}")


def guarded(message: str, options) -> None:
    try:
        run(message, options)
    except Exception as error:  # a scripted run must never kill the fake silently
        sys.stderr.write(f"fake-pi: run failed: {error}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slow", type=float, default=0.0, help="seconds between run steps")
    parser.add_argument("--die-code", type=int, default=0, help="exit this code after the first prompt")
    parser.add_argument("--no-tool", action="store_true", help="run without a tool call")
    parser.add_argument("--model", default="fake/model")
    options = parser.parse_known_args()[0]  # the supervisor also passes pi's own flags
    sys.stderr.write("fake-pi: ready\n")
    sys.stderr.flush()
    for line in sys.stdin.buffer:
        try:
            command = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            response(None, "parse", success=False, error=f"bad JSON: {error}")
            continue
        if isinstance(command, dict):
            handle(command, options)
    return 0


if __name__ == "__main__":
    sys.exit(main())
