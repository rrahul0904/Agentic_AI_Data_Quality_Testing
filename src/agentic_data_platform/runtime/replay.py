"""Read-only runtime session replay assembled from persisted evidence."""

from __future__ import annotations

from typing import Any

from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.tracing.store import TraceStore


def replay_session(store: RuntimeStore, traces: TraceStore, session_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    if session is None:
        raise KeyError(f"session not found: {session_id}")
    messages = store.messages(session_id)
    generations = store.generations(session_id)
    tool_calls = store.tool_calls(session_id)
    trace_summaries = [item for item in traces.traces(limit=1000) if item.get("session_id") == session_id]
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for generation in generations:
        raw = generation.get("usage") or {}
        input_tokens = int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0)
        output_tokens = int(raw.get("output_tokens") or raw.get("completion_tokens") or 0)
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens
        usage["total_tokens"] += int(raw.get("total_tokens") or input_tokens + output_tokens)
    errors = [{"tool": item["tool"], "status": item["status"], "result": item.get("result")} for item in tool_calls if str(item.get("status")).upper() == "ERROR"]
    assistants = [item for item in messages if item.get("role") == "assistant"]
    return {
        "session": session,
        "conversation_timeline": messages,
        "generation_timeline": generations,
        "tool_timeline": tool_calls,
        "token_totals": usage,
        "cost": None,
        "errors": errors,
        "loop_detection": {"detected": any("loop" in str(error).casefold() for error in errors), "source": "recorded errors only"},
        "trace_ids": [item["trace_id"] for item in trace_summaries],
        "final_outcome": assistants[-1]["content"] if assistants else None,
        "mode": "RECORDED_REPLAY",
        "read_only": True,
        "reexecuted": False,
    }
