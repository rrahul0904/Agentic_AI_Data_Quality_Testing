from __future__ import annotations

import json

from agentic_data_platform.memory import MemoryStore
from agentic_data_platform.plugins import PluginManager
from agentic_data_platform.providers import ProviderResponse, ScriptedProvider
from agentic_data_platform.runtime import AgentRuntime, RuntimeStore
from agentic_data_platform.runtime.context_sources import ContextSourceManager
from agentic_data_platform.skills import SkillService
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tracing import TraceStore
from agentic_data_platform.training import TrainingStore


def test_runtime_injects_bounded_memory_training_and_enabled_skills(tmp_path):
    memory = MemoryStore(tmp_path / "memory.db")
    memory_id = memory.save_memory(
        "fact_reservation grain is reservation_id",
        project_id="hotel",
        tags=["reservation", "dbt"],
    )
    training = TrainingStore(tmp_path / "training.db")
    training.ingest_text(
        "docs/reservation.md",
        "Reservation models must preserve reservation_id and use dbt lineage evidence.",
    )
    skills = SkillService(
        tmp_path,
        state_path=tmp_path / ".ade" / "skills.db",
    )
    skills.install("sql-review")

    context_sources = ContextSourceManager(
        memory,
        training_store=training,
        skill_service=skills,
    )
    store = RuntimeStore(tmp_path / "runtime.db")
    traces = TraceStore(tmp_path / "traces.db")
    session = store.create_session(project_id="hotel")
    provider = ScriptedProvider(
        [ProviderResponse(content="grounded response", finish_reason="stop")]
    )
    plugin_calls = []
    plugins = PluginManager()
    for hook in (
        "session.start",
        "generation.before",
        "generation.after",
        "session.end",
    ):
        plugins.register(
            "capture",
            hook,
            lambda payload, hook=hook: plugin_calls.append((hook, dict(payload))),
        )

    result = AgentRuntime(
        build_tool_registry(),
        store,
        traces,
        context_sources=context_sources,
        plugins=plugins,
    ).run(
        session,
        "Review reservation dbt SQL and lineage",
        provider,
        "test-model",
        project_root=tmp_path,
    )

    assert result["response"] == "grounded response"
    assert memory_id in result["context_sources"]["memory_ids"]
    assert result["context_sources"]["training_chunk_ids"]
    assert "sql-review" in result["context_sources"]["skill_names"]

    request_messages = list(provider.requests[0].messages)
    sources = {
        item.get("context_source")
        for item in request_messages
        if isinstance(item, dict)
    }
    assert {"memory", "training_corpus", "skills"}.issubset(sources)

    applied = training.search("reservation")[0]
    assert applied["applied_count"] == 1

    hooks = [name for name, _ in plugin_calls]
    assert hooks == [
        "session.start",
        "generation.before",
        "generation.after",
        "session.end",
    ]

    trace_tree = traces.tree(result["trace_id"])
    assert trace_tree["event_count"] >= 2
    replay = traces.replay(result["trace_id"])
    assert replay["mode"] == "RECORDED_REPLAY"
    assert replay["reexecuted"] is False
    assert json.loads(traces.export_json(result["trace_id"]))["trace_id"] == result["trace_id"]
    assert "<html>" in traces.export_html(result["trace_id"]).casefold()


def test_disabled_skill_is_not_injected(tmp_path):
    skills = SkillService(tmp_path, state_path=tmp_path / "skills.db")
    skills.install("sql-review")
    skills.set_enabled("sql-review", False)
    selection = ContextSourceManager(skill_service=skills).select(
        "sql review",
        project_root=tmp_path,
    )
    assert "sql-review" not in selection.skill_names


def test_training_applied_count_changes_only_when_context_is_used(tmp_path):
    training = TrainingStore(tmp_path / "training.db")
    training.ingest_text("docs/dbt.md", "dbt reservation lineage quality")
    before = training.search("reservation")[0]
    assert before["applied_count"] == 0

    manager = ContextSourceManager(training_store=training)
    unrelated = manager.select("completely unrelated topic")
    assert unrelated.training_chunk_ids == ()
    assert training.search("reservation")[0]["applied_count"] == 0

    related = manager.select("reservation lineage")
    assert related.training_chunk_ids
    assert training.search("reservation")[0]["applied_count"] == 1
