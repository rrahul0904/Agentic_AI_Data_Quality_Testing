from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .anthropic import AnthropicProvider
from .azure import AzureOpenAIProvider
from .base import Provider
from .bedrock import BedrockProvider
from .gemini import GeminiProvider, VertexAIProvider
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
    required_envs: tuple[str, ...] = ()


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
    "ollama": ProviderSpec(
        "ollama",
        "openai-compatible",
        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        None,
        notes="Local Ollama OpenAI-compatible endpoint; connectivity is checked separately.",
    ),
    "lm-studio": ProviderSpec(
        "lm-studio",
        "openai-compatible",
        os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
        None,
        notes="Local LM Studio OpenAI-compatible endpoint; live connectivity is verified on use.",
    ),
    "cohere": ProviderSpec(
        "cohere",
        "openai-compatible",
        os.getenv("COHERE_OPENAI_BASE_URL", "https://api.cohere.ai/compatibility/v1"),
        "COHERE_API_KEY",
        notes="Uses Cohere's OpenAI-compatible API surface.",
    ),
    "databricks-ai-gateway": ProviderSpec(
        "databricks-ai-gateway",
        "openai-compatible",
        os.getenv("DATABRICKS_AI_GATEWAY_URL", ""),
        "DATABRICKS_TOKEN",
        required_envs=("DATABRICKS_AI_GATEWAY_URL",),
        notes="Requires an authorized Databricks AI Gateway / serving endpoint URL.",
    ),
    "snowflake-cortex": ProviderSpec(
        "snowflake-cortex",
        "openai-compatible",
        os.getenv("SNOWFLAKE_CORTEX_BASE_URL", ""),
        "SNOWFLAKE_CORTEX_TOKEN",
        required_envs=("SNOWFLAKE_CORTEX_BASE_URL",),
        notes="Configured only when an authorized Snowflake Cortex OpenAI-compatible endpoint is supplied.",
    ),
    "github-copilot": ProviderSpec(
        "github-copilot",
        "openai-compatible",
        os.getenv("GITHUB_COPILOT_BASE_URL", "https://api.githubcopilot.com"),
        "GITHUB_COPILOT_TOKEN",
        notes="Available only with an explicitly authorized GitHub Copilot integration token.",
    ),
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

        gemini = ProviderSpec(
            "gemini",
            "gemini-generate-content",
            "https://generativelanguage.googleapis.com/v1beta",
            "GEMINI_API_KEY",
            supports_reasoning=True,
        )
        self.register(
            gemini,
            lambda: GeminiProvider(os.getenv("GEMINI_API_KEY")),
        )

        azure = ProviderSpec(
            "azure-openai",
            "azure-openai",
            os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            "AZURE_OPENAI_API_KEY",
            supports_reasoning=True,
            required_envs=("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"),
        )
        self.register(
            azure,
            lambda: AzureOpenAIProvider(
                os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                os.getenv("AZURE_OPENAI_API_KEY"),
                os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            ),
        )

        vertex = ProviderSpec(
            "vertex",
            "vertex-gemini",
            "https://aiplatform.googleapis.com",
            "GOOGLE_CLOUD_ACCESS_TOKEN",
            supports_reasoning=True,
            required_envs=("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"),
        )
        self.register(
            vertex,
            lambda: VertexAIProvider(
                os.getenv("GOOGLE_CLOUD_PROJECT", ""),
                os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
                os.getenv("GOOGLE_CLOUD_ACCESS_TOKEN"),
            ),
        )

        bedrock = ProviderSpec(
            "bedrock",
            "aws-bedrock-converse",
            "aws://bedrock-runtime",
            None,
            supports_reasoning=True,
            notes="Uses the AWS credential provider chain; live auth is verified on use.",
        )
        self.register(
            bedrock,
            lambda: BedrockProvider(
                region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
            ),
        )

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
                "configured": (
                    (bool(os.getenv(spec.api_key_env)) if spec.api_key_env else True)
                    and all(bool(os.getenv(name)) for name in spec.required_envs)
                ),
                "required_envs": list(spec.required_envs),
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
