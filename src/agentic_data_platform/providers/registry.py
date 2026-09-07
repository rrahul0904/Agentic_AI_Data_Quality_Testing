from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .anthropic import AnthropicProvider
from .base import Provider
from .openai_compatible import OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    protocol: str
    base_url: str
    api_key_env: str | None
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_reasoning: bool = False
    notes: str = ""


_OPENAI_COMPATIBLE: dict[str, ProviderSpec] = {
    "openai": ProviderSpec("openai", "openai-compatible", "https://api.openai.com/v1", "OPENAI_API_KEY", supports_reasoning=True),
    "openrouter": ProviderSpec("openrouter", "openai-compatible", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", supports_reasoning=True),
    "groq": ProviderSpec("groq", "openai-compatible", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "mistral": ProviderSpec("mistral", "openai-compatible", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "together": ProviderSpec("together", "openai-compatible", "https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "xai": ProviderSpec("xai", "openai-compatible", "https://api.x.ai/v1", "XAI_API_KEY", supports_reasoning=True),
    "deepinfra": ProviderSpec("deepinfra", "openai-compatible", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
    "nvidia": ProviderSpec("nvidia", "openai-compatible", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "cerebras": ProviderSpec("cerebras", "openai-compatible", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "perplexity": ProviderSpec("perplexity", "openai-compatible", "https://api.perplexity.ai", "PERPLEXITY_API_KEY"),
    "vercel": ProviderSpec("vercel", "openai-compatible", "https://ai-gateway.vercel.sh/v1", "AI_GATEWAY_API_KEY"),
}


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Provider]] = {}
        self._specs: dict[str, ProviderSpec] = {}
        for name, spec in _OPENAI_COMPATIBLE.items():
            self.register(
                spec,
                lambda spec=spec: OpenAICompatibleProvider(
                    spec.name,
                    spec.base_url,
                    os.getenv(spec.api_key_env) if spec.api_key_env else None,
                ),
            )
        anthropic = ProviderSpec("anthropic", "anthropic-messages", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", supports_reasoning=True)
        self.register(anthropic, lambda: AnthropicProvider())

    def register(self, spec: ProviderSpec, factory: Callable[[], Provider]) -> None:
        self._specs[spec.name] = spec
        self._factories[spec.name] = factory

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def specs(self) -> list[dict[str, object]]:
        return [
            {
                "name": spec.name,
                "protocol": spec.protocol,
                "base_url": spec.base_url,
                "api_key_env": spec.api_key_env,
                "configured": bool(os.getenv(spec.api_key_env)) if spec.api_key_env else True,
                "supports_tools": spec.supports_tools,
                "supports_streaming": spec.supports_streaming,
                "supports_reasoning": spec.supports_reasoning,
                "notes": spec.notes,
            }
            for spec in (self._specs[name] for name in self.names())
        ]

    def create(self, name: str) -> Provider:
        try:
            factory = self._factories[name]
        except KeyError as exc:
            raise KeyError(f"provider not registered: {name}") from exc
        return factory()
