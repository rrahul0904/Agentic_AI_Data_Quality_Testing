from __future__ import annotations

import json
from typing import Any, Iterable


def canonical_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls") or []
    result = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        args = item.get("args", {})
        call_id = item.get("id") or item.get("call_id")
        if name:
            result.append({"id": str(call_id or ""), "name": str(name), "args": dict(args or {})})
    return result


def to_openai_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for original in messages:
        role = str(original.get("role") or "user")
        content = original.get("content", "")
        if role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": content if content != "" else None}
            calls = canonical_tool_calls(original)
            if calls:
                item["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["args"], default=str, sort_keys=True),
                        },
                    }
                    for call in calls
                ]
            result.append(item)
            continue
        if role == "tool":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": str(original.get("tool_call_id") or ""),
                    "content": str(content or ""),
                }
            )
            continue
        result.append({"role": role, "content": content})
    return result


def to_anthropic_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for original in messages:
        role = str(original.get("role") or "user")
        if role == "system":
            continue
        content = original.get("content", "")
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            if content:
                blocks.append({"type": "text", "text": str(content)})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call["args"],
                }
                for call in canonical_tool_calls(original)
            )
            result.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(original.get("tool_call_id") or ""),
                "content": str(content or ""),
            }
            if result and result[-1].get("role") == "user" and isinstance(result[-1].get("content"), list):
                prior = result[-1]["content"]
                if prior and all(isinstance(item, dict) and item.get("type") == "tool_result" for item in prior):
                    prior.append(block)
                    continue
            result.append({"role": "user", "content": [block]})
            continue
        result.append({"role": "user", "content": content})
    return result


def to_gemini_contents(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for original in messages:
        role = str(original.get("role") or "user")
        if role == "system":
            continue
        content = original.get("content")
        if role == "assistant":
            parts: list[dict[str, Any]] = []
            if content:
                parts.append({"text": str(content)})
            parts.extend(
                {
                    "functionCall": {
                        "name": call["name"],
                        "args": call["args"],
                    }
                }
                for call in canonical_tool_calls(original)
            )
            result.append({"role": "model", "parts": parts or [{"text": ""}]})
            continue
        if role == "tool":
            part = {
                "functionResponse": {
                    "name": str(original.get("name") or "tool"),
                    "response": {
                        "content": str(content or ""),
                        "status": original.get("status"),
                    },
                }
            }
            if result and result[-1].get("role") == "user":
                prior = result[-1].get("parts")
                if isinstance(prior, list) and prior and all("functionResponse" in item for item in prior if isinstance(item, dict)):
                    prior.append(part)
                    continue
            result.append({"role": "user", "parts": [part]})
            continue
        if isinstance(content, list):
            parts = [{"text": str(item.get("text") if isinstance(item, dict) and "text" in item else item)} for item in content]
        else:
            parts = [{"text": str(content or "")}]
        result.append({"role": "user", "parts": parts})
    return result
