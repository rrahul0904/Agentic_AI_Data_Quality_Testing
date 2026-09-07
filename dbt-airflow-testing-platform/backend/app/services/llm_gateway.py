"""LLM Gateway (Architecture spec Section 23 / Master Prompt Section 21).

Provider-neutral by design -- callers depend on `LLMGateway`, never on
`openai` directly, so swapping providers later doesn't touch agent code.
Every call returns real token usage so it can be logged (AI cost
accounting, Architecture spec Section 30.2) -- there is no path that
silently spends tokens without a record.

This is deliberately the *only* file in the codebase that imports an LLM
SDK. If a second provider is added later, it becomes a second class here,
not a second call site scattered through the agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from ..config import settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMUsage:
    provider: str
    model: str
    tokens_in: int | None
    tokens_out: int | None


class LLMGatewayError(RuntimeError):
    pass


class LLMGateway(ABC):
    @abstractmethod
    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> tuple[T, LLMUsage]:
        """Calls the model with a structured-output contract and returns the
        parsed, schema-validated response plus real token usage. Must raise
        LLMGatewayError (not swallow) on any failure -- callers decide
        whether "the LLM was unreachable" should downgrade a claim to
        UNVERIFIED or fail loudly; this layer never guesses."""
        ...


class OpenAIGateway(LLMGateway):
    def __init__(self, api_key: str, model: str, timeout_seconds: int = 30):
        from openai import OpenAI  # local import: keeps the SDK dependency optional at import time

        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> tuple[T, LLMUsage]:
        import openai as openai_sdk

        try:
            completion = self._client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_model,
            )
        except openai_sdk.APIError as exc:
            raise LLMGatewayError(f"OpenAI API error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.parsed is None:
            raise LLMGatewayError(f"OpenAI returned no parsed structured output (finish_reason={choice.finish_reason})")

        usage = completion.usage
        return choice.message.parsed, LLMUsage(
            provider="openai",
            model=self._model,
            tokens_in=usage.prompt_tokens if usage else None,
            tokens_out=usage.completion_tokens if usage else None,
        )


def get_default_gateway() -> LLMGateway | None:
    """Returns None (never raises) when no provider is configured, so
    callers can cleanly fall back to "no LLM available" rather than crash
    the deterministic path an LLM is only ever an escalation from."""
    if not settings.openai_api_key:
        return None
    return OpenAIGateway(settings.openai_api_key, settings.openai_model, settings.llm_request_timeout_seconds)
