#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agentic_data_platform.providers import ProviderRegistry
from agentic_data_platform.runtime import AgentRuntime, RuntimeStore
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolRegistry
from agentic_data_platform.tracing import TraceStore


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"BLOCKED_EXTERNAL: required environment variable is missing: {name}")
    return value


def main() -> None:
    provider_name = os.getenv("ADE_LIVE_AGENT_PROVIDER", "openai")
    model = required("ADE_LIVE_AGENT_MODEL")
    registry_all = build_tool_registry()
    registry = ToolRegistry()
    registry.register(registry_all.describe("sql_classify"))
    provider = ProviderRegistry().create(provider_name)

    with tempfile.TemporaryDirectory() as tmp:
        store = RuntimeStore(Path(tmp) / "runtime.db")
        traces = TraceStore(Path(tmp) / "traces.db")
        session = store.create_session(provider=provider_name, model=model, title="live-agent-e2e")
        store.add_message(
            session,
            "system",
            "You are a live agent verification harness. Your FIRST action MUST be to call the only available tool, "
            "sql_classify, with SQL exactly SELECT 1. After receiving the tool result, reply with LIVE_AGENT_PASS "
            "and a one-sentence evidence summary. Do not claim the tool ran unless you received its result.",
        )
        result = AgentRuntime(registry, store, traces, max_steps=4, repeated_tool_limit=2).run(
            session,
            "Verify the SQL tool boundary now.",
            provider,
            model,
        )
        messages = store.messages(session)
        tool_messages = [message for message in messages if message["role"] == "tool"]
        if not tool_messages:
            raise SystemExit("live LLM returned without invoking the governed tool")
        if "LIVE_AGENT_PASS" not in str(result.get("response") or ""):
            raise SystemExit(f"live LLM did not complete the verification contract: {result.get('response')!r}")
        print(json.dumps({
            "status": "PASS",
            "mode": "LIVE_LLM",
            "provider": provider_name,
            "model": model,
            "trace_id": result["trace_id"],
            "steps": result["steps"],
            "tool_calls": [
                {
                    "name": message["metadata"].get("name"),
                    "status": message["metadata"].get("status"),
                    "content": json.loads(message["content"]),
                }
                for message in tool_messages
            ],
            "response": result["response"],
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
