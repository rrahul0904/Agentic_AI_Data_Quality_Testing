from __future__ import annotations

from typing import Any

import httpx

from .base import ProviderRequest, ProviderResponse, ToolCall, Usage


def _gemini_payload(request: ProviderRequest) -> dict[str, Any]:
    system_parts = [
        str(message.get("content") or "")
        for message in request.messages
        if message.get("role") == "system"
    ]
    contents = []
    for message in request.messages:
        role = message.get("role")
        if role == "system":
            continue
        target_role = "model" if role == "assistant" else "user"
        content = message.get("content")
        if isinstance(content, str):
            parts = [{"text": content}]
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool-result":
                    parts.append(
                        {
                            "functionResponse": {
                                "name": item.get("name") or item.get("toolName") or "tool",
                                "response": item.get("result") or item.get("content") or {},
                            }
                        }
                    )
                elif isinstance(item, dict) and item.get("text") is not None:
                    parts.append({"text": str(item["text"])})
                else:
                    parts.append({"text": str(item)})
        else:
            parts = [{"text": str(content or "")}]
        contents.append({"role": target_role, "parts": parts})

    payload: dict[str, Any] = {"contents": contents}
    if system_parts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}]
        }
    if request.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": item["name"],
                        "description": item.get("description", ""),
                        "parameters": item.get("input_schema") or {"type": "object"},
                    }
                    for item in request.tools
                ]
            }
        ]
    generation: dict[str, Any] = {}
    if request.temperature is not None:
        generation["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        generation["maxOutputTokens"] = request.max_output_tokens
    if generation:
        payload["generationConfig"] = generation
    return payload


def _gemini_response(data: dict[str, Any]) -> ProviderResponse:
    candidate = (data.get("candidates") or [{}])[0]
    content = candidate.get("content") or {}
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for index, part in enumerate(content.get("parts") or []):
        if part.get("text") is not None:
            text_parts.append(str(part.get("text") or ""))
        if isinstance(part.get("functionCall"), dict):
            call = part["functionCall"]
            calls.append(
                ToolCall(
                    str(call.get("name") or ""),
                    dict(call.get("args") or {}),
                    str(call.get("id") or f"gemini-call-{index}"),
                )
            )
    usage = data.get("usageMetadata") or {}
    return ProviderResponse(
        content="".join(text_parts),
        tool_calls=tuple(calls),
        usage=Usage(
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
            reasoning_tokens=int(usage.get("thoughtsTokenCount") or 0),
            cache_read_tokens=int(usage.get("cachedContentTokenCount") or 0),
        ),
        finish_reason=candidate.get("finishReason"),
        raw=data,
    )


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        params = {"key": self.api_key} if self.api_key else {}
        response = self._client.post(
            f"{self.base_url}/models/{request.model}:generateContent",
            params=params,
            headers={"content-type": "application/json"},
            json=_gemini_payload(request),
        )
        response.raise_for_status()
        return _gemini_response(response.json())


class VertexAIProvider:
    name = "vertex"

    def __init__(
        self,
        project: str,
        location: str,
        access_token: str | None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.project = project
        self.location = location
        self.access_token = access_token
        self._client = client or httpx.Client(timeout=120)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/"
            f"{self.project}/locations/{self.location}/publishers/google/models/"
            f"{request.model}:generateContent"
        )
        headers = {"content-type": "application/json"}
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        response = self._client.post(
            url,
            headers=headers,
            json=_gemini_payload(request),
        )
        response.raise_for_status()
        return _gemini_response(response.json())
