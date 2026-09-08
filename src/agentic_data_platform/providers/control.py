"""Provider control-plane primitives: auth, catalog, model status, budgets and transforms."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agentic_data_platform.providers.registry import ProviderRegistry


MODEL_STATUSES = {"alpha", "beta", "deprecated", "active"}
OUTPUT_TOKEN_FLOOR = 1024


class ProviderControlError(RuntimeError):
    pass


class ProviderAuthError(ProviderControlError):
    pass


class ProviderBudgetError(ProviderControlError):
    pass


def family_vendor(family: str | None) -> str | None:
    if not family:
        return None
    value = family.casefold()
    if value in {"anthropic", "claude"} or value.startswith("claude-"):
        return "anthropic"
    if value == "gemini" or value.startswith("gemini-"):
        return "gemini"
    if value in {"openai", "openai-compatible", "gpt"} or value.startswith("gpt-"):
        return "openai"
    return None


def is_catalog_entry(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("id"), str)
        and isinstance(value.get("models"), Mapping)
    )


def is_catalog(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    return any(is_catalog_entry(item) for item in value.values())


def parse_catalog(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return dict(value) if is_catalog(value) else None


@dataclass(frozen=True)
class ModelRecord:
    provider_id: str
    model_id: str
    name: str
    family: str | None = None
    status: str = "active"
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool = True
    supports_reasoning: bool = False
    modalities: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in MODEL_STATUSES:
            raise ValueError(f"invalid model status: {self.status}")


class ModelCatalog:
    def __init__(self, models: Iterable[ModelRecord] = ()) -> None:
        self._models: dict[tuple[str, str], ModelRecord] = {
            (item.provider_id, item.model_id): item for item in models
        }

    @classmethod
    def from_models_dev(cls, payload: Mapping[str, Any]) -> "ModelCatalog":
        models: list[ModelRecord] = []
        for provider_key, provider in payload.items():
            if not is_catalog_entry(provider):
                continue
            provider_id = str(provider.get("id") or provider_key)
            for model_id, raw in provider.get("models", {}).items():
                if not isinstance(raw, Mapping):
                    continue
                status = str(raw.get("status") or "active")
                if status not in MODEL_STATUSES:
                    status = "active"
                limit = raw.get("limit") if isinstance(raw.get("limit"), Mapping) else {}
                modalities = raw.get("modalities") if isinstance(raw.get("modalities"), Mapping) else {}
                inputs = modalities.get("input") if isinstance(modalities, Mapping) else ()
                models.append(
                    ModelRecord(
                        provider_id=provider_id,
                        model_id=str(raw.get("id") or model_id),
                        name=str(raw.get("name") or model_id),
                        family=str(raw.get("family")) if raw.get("family") else None,
                        status=status,
                        context_window=int(limit.get("context")) if limit.get("context") else None,
                        max_output_tokens=int(limit.get("output")) if limit.get("output") else None,
                        supports_tools=bool(raw.get("tool_call", raw.get("tools", True))),
                        supports_reasoning=bool(raw.get("reasoning", False)),
                        modalities=tuple(str(item) for item in (inputs or ())),
                        metadata=dict(raw),
                    )
                )
        return cls(models)

    def add(self, model: ModelRecord) -> None:
        self._models[(model.provider_id, model.model_id)] = model

    def list(
        self,
        *,
        provider_id: str | None = None,
        status: str | None = None,
        supports_tools: bool | None = None,
    ) -> list[ModelRecord]:
        items = list(self._models.values())
        if provider_id:
            items = [item for item in items if item.provider_id == provider_id]
        if status:
            items = [item for item in items if item.status == status]
        if supports_tools is not None:
            items = [item for item in items if item.supports_tools is supports_tools]
        return sorted(items, key=lambda item: (item.provider_id, item.model_id))

    def get(self, provider_id: str, model_id: str) -> ModelRecord:
        try:
            return self._models[(provider_id, model_id)]
        except KeyError as exc:
            raise KeyError(f"model not found: {provider_id}/{model_id}") from exc

    def snapshot(self) -> dict[str, Any]:
        return {
            "models": [asdict(item) for item in self.list()],
            "count": len(self._models),
        }

    def status(self, provider_id: str, model_id: str) -> str:
        return self.get(provider_id, model_id).status

    def find(
        self,
        query: str,
        *,
        provider_id: str | None = None,
        include_deprecated: bool = False,
    ) -> list[ModelRecord]:
        needle = query.casefold().strip()
        items = self.list(provider_id=provider_id)
        if not include_deprecated:
            items = [item for item in items if item.status != "deprecated"]
        return [
            item
            for item in items
            if needle in item.model_id.casefold()
            or needle in item.name.casefold()
            or needle in (item.family or "").casefold()
        ]


def configured_auth(registry: ProviderRegistry | None = None) -> dict[str, Any]:
    provider_registry = registry or ProviderRegistry()
    providers = []
    for spec in provider_registry.specs():
        env_name = spec.get("api_key_env")
        providers.append(
            {
                "provider": spec["name"],
                "method": "api" if env_name else "none",
                "configured": bool(spec.get("configured")),
                "credential_env": env_name,
                "required_envs": list(spec.get("required_envs") or ()),
            }
        )
    return {"providers": providers}


def provider_auth_status(provider: str, registry: ProviderRegistry | None = None) -> dict[str, Any]:
    statuses = {
        item["provider"]: item
        for item in configured_auth(registry)["providers"]
    }
    if provider not in statuses:
        raise KeyError(f"provider not registered: {provider}")
    return statuses[provider]


def sanitize_surrogates(value: str) -> str:
    return value.encode("utf-8", "replace").decode("utf-8", "replace")


def normalize_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    provider: str,
    model_id: str = "",
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        item = dict(message)
        content = item.get("content")
        if isinstance(content, str):
            item["content"] = sanitize_surrogates(content)
            if provider in {"anthropic", "bedrock"} and not item["content"]:
                continue
        elif isinstance(content, list):
            cleaned = []
            for part in content:
                if not isinstance(part, Mapping):
                    cleaned.append(part)
                    continue
                piece = dict(part)
                if isinstance(piece.get("text"), str):
                    piece["text"] = sanitize_surrogates(piece["text"])
                if (
                    provider in {"anthropic", "bedrock"}
                    and piece.get("type") in {"text", "reasoning"}
                    and not str(piece.get("text") or "")
                    and not piece.get("signature")
                    and not piece.get("redactedData")
                ):
                    continue
                if "toolCallId" in piece and (
                    provider == "anthropic"
                    or "claude" in model_id.casefold()
                ):
                    piece["toolCallId"] = re.sub(r"[^A-Za-z0-9_-]", "_", str(piece["toolCallId"]))
                if "toolCallId" in piece and provider == "mistral":
                    token = re.sub(r"[^A-Za-z0-9]", "", str(piece["toolCallId"]))[:9]
                    piece["toolCallId"] = token.ljust(9, "0")
                cleaned.append(piece)
            if provider in {"anthropic", "bedrock"} and not cleaned:
                continue
            item["content"] = cleaned
        result.append(item)

    if provider == "mistral":
        repaired: list[dict[str, Any]] = []
        for index, item in enumerate(result):
            repaired.append(item)
            next_item = result[index + 1] if index + 1 < len(result) else None
            if item.get("role") == "tool" and next_item and next_item.get("role") == "user":
                repaired.append({"role": "assistant", "content": "Done."})
        result = repaired
    return result


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_count = sum(ord(char) <= 127 for char in text)
    non_ascii = len(text) - ascii_count
    emoji_like = sum(ord(char) > 0xFFFF for char in text)
    base = math.ceil(ascii_count / 3.7) + non_ascii + emoji_like
    dense_runs = re.findall(r"[A-Za-z0-9+/_=-]{32,}", text)
    dense_extra = sum(math.ceil(len(run) * 0.75) for run in dense_runs if len(set(run)) >= 6)
    return base + dense_extra


def estimate_message_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += 4
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, Mapping):
                    if isinstance(part.get("text"), str):
                        total += estimate_text_tokens(str(part["text"]))
                    part_type = str(part.get("type") or "")
                    if part_type.startswith("image"):
                        total += 2048
                    elif part_type in {"file", "media"}:
                        total += 16384
                    elif part_type == "audio":
                        total += 8192
                    elif part_type == "video":
                        total += 8192
    return total


def output_token_budget(
    model: ModelRecord,
    messages: Sequence[Mapping[str, Any]],
    *,
    requested: int | None = None,
    floor: int = OUTPUT_TOKEN_FLOOR,
) -> dict[str, Any]:
    input_tokens = estimate_message_tokens(messages)
    context = model.context_window
    model_max = model.max_output_tokens
    requested_value = int(requested or model_max or 32000)
    if model_max is not None:
        requested_value = min(requested_value, model_max)
    if context is None:
        return {
            "input_tokens": input_tokens,
            "requested": requested_value,
            "allowed": requested_value,
            "context_window": None,
            "clamped": False,
        }
    margin = max(512, math.ceil(context * 0.02))
    available = max(0, context - input_tokens - margin)
    allowed = min(requested_value, available)
    if allowed < floor:
        raise ProviderBudgetError(
            f"context budget exceeded for {model.provider_id}/{model.model_id}: "
            f"input={input_tokens}, requested={requested_value}, context={context}, floor={floor}"
        )
    return {
        "input_tokens": input_tokens,
        "requested": requested_value,
        "allowed": allowed,
        "context_window": context,
        "margin": margin,
        "clamped": allowed != requested_value,
    }


def load_catalog_snapshot(path: str | Path) -> ModelCatalog:
    source = Path(path)
    payload = parse_catalog(source.read_text())
    if payload is None:
        raise ValueError(f"invalid provider model catalog snapshot: {source}")
    return ModelCatalog.from_models_dev(payload)
