from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import ProviderRequest, ProviderResponse, ToolCall, Usage
from .messages import to_openai_messages


def openai_tools(tools):
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item.get("description", ""),
                "parameters": item.get("input_schema") or {"type": "object"},
            },
        }
        for item in tools
    ]


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None,
        *,
        headers: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        self._client = client or httpx.Client(timeout=120)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        headers = {"content-type": "application/json", **self.headers}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {"model": request.model, "messages": to_openai_messages(request.messages)}
        if request.tools:
            payload["tools"] = openai_tools(request.tools)
            payload["tool_choice"] = "auto"
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            if self.name == "openai":
                payload["max_completion_tokens"] = request.max_output_tokens
            else:
                payload["max_tokens"] = request.max_output_tokens
        if self.name == "openai":
            reasoning_effort = str(
                request.metadata.get("reasoning_effort")
                or os.getenv("ADE_OPENAI_REASONING_EFFORT", "low")
            ).strip()
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
        response = self._client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            arguments = function.get("arguments") or "{}"
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {"_raw": arguments}
            calls.append(ToolCall(str(function.get("name") or ""), args, str(item.get("id") or "")))
        usage = data.get("usage") or {}
        return ProviderResponse(
            content=str(message.get("content") or ""),
            tool_calls=tuple(calls),
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                reasoning_tokens=int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                cache_read_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            ),
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )
