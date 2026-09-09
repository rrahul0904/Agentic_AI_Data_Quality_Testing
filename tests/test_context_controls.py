from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.advanced_capabilities import compact_context, select_context
from agentic_data_platform.api.app import create_app
from agentic_data_platform.tools.builtin import build_tool_registry


def _items():
    return [
        {
            "id": "critical",
            "text": "critical evidence " * 100,
            "evidence_rank": 10,
            "relevance": 10,
            "recency": 10,
        },
        {
            "id": "recent",
            "text": "recent evidence " * 120,
            "evidence_rank": 5,
            "relevance": 8,
            "recency": 9,
        },
        {
            "id": "noise",
            "text": "irrelevant noise " * 140,
            "evidence_rank": 1,
            "relevance": 1,
            "recency": 1,
        },
    ]


def test_pinned_context_is_preserved_even_when_lower_rank():
    items = _items()
    items[2]["evidence_rank"] = 0
    result = select_context(
        items,
        budget_tokens=700,
        pinned_ids=["noise"],
    )

    assert result["status"] == "PASS"
    selected = {item["id"]: item for item in result["selected"]}
    assert "noise" in selected
    assert selected["noise"]["pinned"] is True
    assert result["pinned_ids"] == ["noise"]


def test_excluded_context_is_never_selected():
    result = select_context(
        _items(),
        budget_tokens=2000,
        excluded_ids=["critical"],
    )
    assert result["status"] == "PASS"
    assert "critical" not in {item["id"] for item in result["selected"]}
    assert "critical" in result["excluded_ids"]


def test_pin_exclude_conflict_is_rejected():
    result = select_context(
        _items(),
        pinned_ids=["critical"],
        excluded_ids=["critical"],
    )
    assert result["status"] == "INVALID_CONTEXT_POLICY"
    assert result["conflicts"] == ["critical"]


def test_pinned_context_cannot_silently_overflow_provider_budget():
    result = select_context(
        _items(),
        budget_tokens=1000,
        provider_limit_tokens=128,
        pinned_ids=["critical"],
    )
    assert result["status"] == "BLOCKED_PIN_BUDGET"
    assert result["provider_limit_tokens"] if "provider_limit_tokens" in result else result["budget_tokens"] == 128


def test_provider_limit_reduces_effective_budget():
    result = select_context(
        _items(),
        budget_tokens=2000,
        provider="openai:gpt-test",
        provider_limit_tokens=500,
    )
    assert result["status"] == "PASS"
    assert result["budget_tokens"] == 500
    assert result["provider"] == "openai:gpt-test"
    assert result["provider_chars_per_token"] == 4.0


def test_compaction_preserves_pinned_text_and_records_boundaries():
    items = _items()
    original = items[0]["text"]
    result = compact_context(
        items,
        budget_tokens=700,
        pinned_ids=["critical"],
        summary_chars=180,
    )

    assert result["status"] == "PASS"
    assert result["compacted"] is True
    pinned = next(item for item in result["selected"] if item["id"] == "critical")
    assert pinned["text"] == original
    assert pinned["pinned"] is True
    assert result["compaction_boundaries"]
    assert result["compaction_fingerprint"]
    assert all(boundary["id"] != "critical" for boundary in result["compaction_boundaries"])


def test_no_overflow_skips_compaction():
    result = compact_context(
        [{"id": "small", "text": "short", "evidence_rank": 1}],
        budget_tokens=1000,
    )
    assert result["status"] == "PASS"
    assert result["compacted"] is False
    assert result["compaction_boundaries"] == []


def test_context_tools_and_api_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {"context_select", "context_compact"} <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    advanced = response.json()["advanced"]
    assert {"context-select", "context-compact"} <= set(advanced)
