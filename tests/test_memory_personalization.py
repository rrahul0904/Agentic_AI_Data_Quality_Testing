from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.memory import MemoryStore
from agentic_data_platform.tools.builtin import build_tool_registry


def test_global_memory_is_visible_across_projects_but_project_memory_is_isolated(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    global_id = store.save_memory("Global naming standard", scope="global")
    p1_id = store.save_memory("Project one fact", scope="project", project_id="p1")
    store.save_memory("Project two fact", scope="project", project_id="p2")

    p1 = store.list_memories(project_id="p1")
    p1_ids = {item["memory_id"] for item in p1}
    assert global_id in p1_ids
    assert p1_id in p1_ids
    assert all(item["content"] != "Project two fact" for item in p1)

    p2 = store.list_memories(project_id="p2")
    assert all(item["content"] != "Project one fact" for item in p2)


def test_disabled_memory_refuses_to_write_and_can_be_reenabled(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    configured = store.configure_memory(scope="project", project_id="p1", enabled=False)
    assert configured["enabled"] is False

    with pytest.raises(PermissionError, match="memory is disabled"):
        store.save_memory("should not persist", scope="project", project_id="p1")

    assert store.list_memories(scope="project", project_id="p1") == []

    store.configure_memory(scope="project", project_id="p1", enabled=True)
    memory_id = store.save_memory("now durable", scope="project", project_id="p1")
    assert memory_id


def test_temporary_state_and_secret_like_values_are_not_persisted(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    with pytest.raises(ValueError, match="temporary task state"):
        store.save_memory(
            "temporary execution note",
            scope="project",
            project_id="p1",
            kind="temporary",
        )

    with pytest.raises(ValueError, match="secret-like"):
        store.save_memory(
            "api_key=abcdefghijklmnopqrstuvwxyz123456",
            scope="project",
            project_id="p1",
        )

    with pytest.raises(ValueError, match="secret-like"):
        store.configure_memory(
            scope="global",
            instructions="Use password=super-secret-password for tests",
        )

    assert store.list_memories(project_id="p1") == []


def test_memory_update_and_scoped_reset_are_inspectable(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    first = store.save_memory("old fact", scope="project", project_id="p1")
    store.save_memory("keep p2", scope="project", project_id="p2")

    updated = store.update_memory(
        first,
        content="new fact",
        tags=["verified"],
        citations=["run:123"],
    )
    assert updated["content"] == "new fact"
    assert updated["tags"] == ["verified"]
    assert updated["citations"] == ["run:123"]

    reset = store.reset_memories(scope="project", project_id="p1")
    assert reset["removed"] == 1
    assert store.list_memories(scope="project", project_id="p1") == []
    assert [item["content"] for item in store.list_memories(scope="project", project_id="p2")] == ["keep p2"]


def test_personalization_composes_global_and_project_settings(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.configure_memory(
        scope="global",
        instructions="Always show evidence.",
        tool_preferences={"web_search": "audited"},
        runtime_preferences={"model": "balanced"},
    )
    store.configure_memory(
        scope="project",
        project_id="p1",
        instructions="Prefer dbt artifacts for lineage.",
        tool_preferences={"sql": "read_first"},
        runtime_preferences={"model": "coding"},
    )

    result = store.personalization(project_id="p1")
    assert result["effective"]["enabled"] is True
    assert result["effective"]["instructions"] == [
        "Always show evidence.",
        "Prefer dbt artifacts for lineage.",
    ]
    assert result["effective"]["tool_preferences"] == {
        "web_search": "audited",
        "sql": "read_first",
    }
    assert result["effective"]["runtime_preferences"]["model"] == "coding"


def test_memory_tool_and_api_surfaces_expose_governed_personalization():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "memory_save",
        "memory_list",
        "memory_search",
        "memory_settings",
        "memory_personalization",
        "memory_configure",
        "memory_update",
        "memory_reset",
        "memory_remove",
    } <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    memory = response.json()["memory"]
    assert set(memory) == {
        "save",
        "list",
        "search",
        "settings",
        "personalization",
        "configure",
        "update",
        "reset",
        "remove",
    }
