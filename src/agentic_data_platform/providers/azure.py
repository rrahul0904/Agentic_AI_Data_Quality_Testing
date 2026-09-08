from __future__ import annotations

import json
from typing import Any

import httpx

from .base import ProviderRequest, ProviderResponse, ToolCall, Usage
from .openai_compatible import openai_tools
from .messages import to_openai_messages


class AzureOpenAIProvider:
    name = "azure-openai"

    def __init__(
        self,
        endpoint: str,
        api_key: str | None,
        deployment: str,
        *,
        api_version: str = "2024-10-21",
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self._client = client or httpx.Client(timeout=120)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        payload: dict[str, Any] = {
            "messages": to_openai_messages(request.messages),
        }
        if request.tools:
            payload["tools"] = openai_tools(request.tools)
            payload["tool_choice"] = "auto"
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        response = self._client.post(
            f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions",
            params={"api-version": self.api_version},
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {"_raw": raw_args}
            calls.append(
                ToolCall(
                    str(function.get("name") or ""),
                    args,
                    str(item.get("id") or ""),
                )
            )
        usage = data.get("usage") or {}
        return ProviderResponse(
            content=str(message.get("content") or ""),
            tool_calls=tuple(calls),
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                reasoning_tokens=int(
                    (usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    )
                    or 0
                ),
                cache_read_tokens=int(
                    (usage.get("prompt_tokens_details") or {}).get(
                        "cached_tokens"
                    )
                    or 0
                ),
            ),
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )
