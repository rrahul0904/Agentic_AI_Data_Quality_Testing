from __future__ import annotations

from typing import Any

from .base import ProviderRequest, ProviderResponse, ToolCall, Usage


class BedrockProvider:
    name = "bedrock"

    def __init__(
        self,
        *,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.region = region
        self._client = client

    def _client_value(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for Bedrock") from exc
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self.region,
        )
        return self._client

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        system = []
        messages = []
        for message in request.messages:
            role = str(message.get("role") or "user")
            content = message.get("content")
            if role == "system":
                system.append({"text": str(content or "")})
                continue
            target_role = "assistant" if role == "assistant" else "user"
            blocks = []
            if isinstance(content, str):
                blocks.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        blocks.append({"text": str(item)})
                        continue
                    item_type = item.get("type")
                    if item_type in {"tool-result", "tool_result"}:
                        blocks.append(
                            {
                                "toolResult": {
                                    "toolUseId": str(
                                        item.get("toolCallId")
                                        or item.get("tool_use_id")
                                        or ""
                                    ),
                                    "content": [
                                        {
                                            "json": item.get("result")
                                            or item.get("content")
                                            or {}
                                        }
                                    ],
                                }
                            }
                        )
                    elif item.get("text") is not None:
                        blocks.append({"text": str(item["text"])})
            messages.append({"role": target_role, "content": blocks})

        kwargs: dict[str, Any] = {
            "modelId": request.model,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": item["name"],
                            "description": item.get("description", ""),
                            "inputSchema": {
                                "json": item.get("input_schema")
                                or {"type": "object"}
                            },
                        }
                    }
                    for item in request.tools
                ]
            }
        inference: dict[str, Any] = {}
        if request.temperature is not None:
            inference["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            inference["maxTokens"] = request.max_output_tokens
        if inference:
            kwargs["inferenceConfig"] = inference

        data = self._client_value().converse(**kwargs)
        output = (data.get("output") or {}).get("message") or {}
        text_parts = []
        calls = []
        for block in output.get("content") or []:
            if block.get("text") is not None:
                text_parts.append(str(block.get("text") or ""))
            if isinstance(block.get("toolUse"), dict):
                tool_use = block["toolUse"]
                calls.append(
                    ToolCall(
                        str(tool_use.get("name") or ""),
                        dict(tool_use.get("input") or {}),
                        str(tool_use.get("toolUseId") or ""),
                    )
                )
        usage = data.get("usage") or {}
        return ProviderResponse(
            content="".join(text_parts),
            tool_calls=tuple(calls),
            usage=Usage(
                input_tokens=int(usage.get("inputTokens") or 0),
                output_tokens=int(usage.get("outputTokens") or 0),
                cache_read_tokens=int(usage.get("cacheReadInputTokens") or 0),
                cache_write_tokens=int(usage.get("cacheWriteInputTokens") or 0),
            ),
            finish_reason=data.get("stopReason"),
            raw=data,
        )
