from __future__ import annotations

from agentic_data_platform.providers.messages import (
    to_anthropic_messages,
    to_gemini_contents,
    to_openai_messages,
)


CANONICAL = [
    {"role": "user", "content": "classify this"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call-1", "name": "sql_classify", "args": {"sql": "SELECT 1"}}],
    },
    {
        "role": "tool",
        "content": '{"status":"PASS"}',
        "tool_call_id": "call-1",
        "name": "sql_classify",
        "status": "SUCCESS",
    },
    {"role": "assistant", "content": "The query is read-only."},
]


def test_openai_tool_turn_is_provider_valid():
    messages = to_openai_messages(CANONICAL)
    assert messages[1]["tool_calls"][0]["function"]["name"] == "sql_classify"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call-1"


def test_anthropic_tool_turn_is_provider_valid():
    messages = to_anthropic_messages(CANONICAL)
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["type"] == "tool_result"


def test_gemini_tool_turn_is_provider_valid():
    messages = to_gemini_contents(CANONICAL)
    assert messages[1]["parts"][0]["functionCall"]["name"] == "sql_classify"
    assert messages[2]["parts"][0]["functionResponse"]["name"] == "sql_classify"
