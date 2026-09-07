from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str

@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None

@dataclass(frozen=True)
class ProviderRequest:
    model: str
    messages: Sequence[dict[str, Any]]
    tools: Sequence[dict[str, Any]] = ()
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ProviderResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

class Provider(Protocol):
    name: str
    def generate(self, request: ProviderRequest) -> ProviderResponse: ...
