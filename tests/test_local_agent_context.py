from __future__ import annotations

from agentic_data_platform.runtime.local_agent import agent_config, ingest_document, knowledge_search


def test_ingested_document_is_retrievable(tmp_path) -> None:
    result = ingest_document(
        tmp_path,
        "revenue-rules.md",
        b"RevPAR equals room revenue divided by available room nights.",
    )
    assert result["status"] == "INDEXED"
    found = knowledge_search(tmp_path, "RevPAR room revenue", limit=5)
    assert found["results"]
    assert found["results"][0]["source"] == "revenue-rules.md"


def test_default_agent_model_is_cost_sensitive(monkeypatch) -> None:
    for name in ("ADE_AGENT_PROVIDER", "ADE_LIVE_AGENT_PROVIDER", "ADE_AGENT_MODEL", "ADE_LIVE_AGENT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config = agent_config()
    assert config["provider"] == "openai"
    assert config["model"] == "gpt-5.6-luna"
