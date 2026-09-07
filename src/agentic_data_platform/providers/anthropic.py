from __future__ import annotations

import os
from typing import Any

import httpx

from .base import ProviderRequest, ProviderResponse, ToolCall, Usage


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://api.anthropic.com/v1",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        system_parts = [str(m.get("content", "")) for m in request.messages if m.get("role") == "system"]
        messages = [dict(m) for m in request.messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens or 4096,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = [
                {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "input_schema": item.get("input_schema") or {"type": "object"},
                }
                for item in request.tools
            ]
        headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        response = self._client.post(f"{self.base_url}/messages", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        text_parts, calls = [], []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        str(block.get("name") or ""),
                        dict(block.get("input") or {}),
                        str(block.get("id") or ""),
                    )
                )
        usage = data.get("usage") or {}
        return ProviderResponse(
            content="".join(text_parts),
            tool_calls=tuple(calls),
            usage=Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            ),
            finish_reason=data.get("stop_reason"),
            raw=data,
        )
