from __future__ import annotations

import json

import pytest

from agentic_data_platform.providers.control import (
    ModelCatalog,
    ModelRecord,
    ProviderBudgetError,
    configured_auth,
    family_vendor,
    normalize_messages,
    output_token_budget,
    parse_catalog,
)


def test_family_vendor_maps_specific_families():
    assert family_vendor("claude-sonnet") == "anthropic"
    assert family_vendor("gemini-flash") == "gemini"
    assert family_vendor("gpt-codex") == "openai"
    assert family_vendor("other") is None


def test_catalog_parser_rejects_junk_and_accepts_valid_provider_map():
    assert parse_catalog("null") is None
    assert parse_catalog("[]") is None
    assert parse_catalog('{"error":"rate limited"}') is None
    payload = {
        "openai": {
            "id": "openai",
            "models": {
                "gpt-test": {
                    "id": "gpt-test",
                    "name": "GPT Test",
                    "family": "gpt",
                    "status": "beta",
                    "limit": {"context": 10000, "output": 2000},
                    "tool_call": True,
                }
            },
        },
        "broken": {"id": 1},
    }
    parsed = parse_catalog(json.dumps(payload))
    assert parsed is not None
    catalog = ModelCatalog.from_models_dev(parsed)
    model = catalog.get("openai", "gpt-test")
    assert model.status == "beta"
    assert model.context_window == 10000
    assert catalog.find("GPT")[0].model_id == "gpt-test"


def test_output_token_budget_clamps_and_blocks_unusable_context():
    model = ModelRecord(
        "openai",
        "gpt-test",
        "GPT Test",
        family="gpt",
        context_window=10000,
        max_output_tokens=5000,
    )
    messages = [{"role": "user", "content": "hello " * 500}]
    result = output_token_budget(model, messages, requested=5000)
    assert result["allowed"] <= 5000
    assert result["allowed"] >= 1024

    tiny = ModelRecord(
        "openai",
        "tiny",
        "Tiny",
        context_window=1200,
        max_output_tokens=1000,
    )
    with pytest.raises(ProviderBudgetError):
        output_token_budget(tiny, [{"role": "user", "content": "x" * 1000}])


def test_provider_message_transform_sanitizes_and_scrubs_tool_ids():
    result = normalize_messages(
        [
            {
                "role": "assistant",
                "content": [{"type": "tool-call", "toolCallId": "bad:id!", "text": "ok"}],
            }
        ],
        provider="anthropic",
        model_id="claude-sonnet",
    )
    assert result[0]["content"][0]["toolCallId"] == "bad_id_"

    mistral = normalize_messages(
        [
            {"role": "tool", "content": [{"type": "tool-result", "toolCallId": "123-abc"}]},
            {"role": "user", "content": "next"},
        ],
        provider="mistral",
    )
    assert mistral[0]["content"][0]["toolCallId"] == "123abc000"
    assert mistral[1]["role"] == "assistant"


def test_configured_auth_never_returns_secret_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    result = configured_auth()
    openai = [item for item in result["providers"] if item["provider"] == "openai"][0]
    assert openai["configured"] is True
    assert "super-secret" not in str(result)
