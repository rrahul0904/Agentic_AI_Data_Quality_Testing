from __future__ import annotations

from agentic_data_platform.models import ActorMode, Capability, Environment, Platform, Risk, ToolRequest
from agentic_data_platform.runtime.local_agent import (
    _scoped_read_only_registry,
    agent_config,
    ingest_document,
    knowledge_search,
)
from agentic_data_platform.tools.registry import ToolDefinition, ToolInvocation, ToolRegistry


def test_ingested_document_is_retrievable_and_redacted(tmp_path) -> None:
    fake_secret = "sk" + "-" + "example-secret-value-" + "1234567890"
    payload = f"OPENAI_API_KEY={fake_secret}\nRevPAR equals room revenue divided by available room nights.".encode()
    result = ingest_document(tmp_path, "revenue-rules.md", payload)
    assert result["status"] == "INDEXED"
    assert result["metadata"]["secrets_redacted"] is True

    found = knowledge_search(tmp_path, "RevPAR room revenue", limit=5)
    assert found["results"]
    corpus = "\n".join(str(item["content"]) for item in found["results"])
    assert fake_secret not in corpus
    assert "[REDACTED]" in corpus


def test_default_agent_model_is_cost_sensitive(monkeypatch) -> None:
    for name in ("ADE_AGENT_PROVIDER", "ADE_LIVE_AGENT_PROVIDER", "ADE_AGENT_MODEL", "ADE_LIVE_AGENT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config = agent_config()
    assert config["provider"] == "openai"
    assert config["model"] == "gpt-5.6-luna"
    assert config["max_steps"] == 8
    assert config["max_output_tokens"] == 1600


def test_read_only_registry_forces_active_project_root(tmp_path) -> None:
    observed = {}
    source = ToolRegistry()
    source.register(
        ToolDefinition(
            name="probe",
            capability=Capability.DISCOVER,
            risk=Risk.READ_ONLY,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: observed.update(args) or {"status": "PASS"},
        )
    )
    source.register(
        ToolDefinition(
            name="mutate",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: {"status": "SHOULD_NOT_RUN"},
        )
    )

    safe = _scoped_read_only_registry(source, tmp_path.resolve())
    assert [item.name for item in safe.definitions()] == ["probe"]
    definition = safe.describe("probe")
    result = safe.invoke(
        ToolInvocation(
            request=ToolRequest(
                tool="probe",
                operation="probe",
                environment=Environment.DEV,
                risk=definition.risk,
                args={"project": "/tmp/escape", "project_root": "/tmp/escape"},
            ),
            run_id="test",
            actor_mode=ActorMode.ANALYST,
        )
    )
    assert result["status"] == "PASS"
    assert observed["project"] == str(tmp_path.resolve())
    assert observed["project_root"] == str(tmp_path.resolve())
