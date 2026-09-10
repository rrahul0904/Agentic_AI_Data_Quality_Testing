from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.session import SessionStore
from agentic_data_platform.tools.builtin import build_tool_registry


def test_todo_done_requires_verification_and_evidence(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session = store.create()
    todo = store.add_todo(session["session_id"], "Run regression")

    with pytest.raises(PermissionError, match="verification passes"):
        store.update_todo(todo["todo_id"], "DONE")

    with pytest.raises(PermissionError, match="without verification evidence"):
        store.update_todo(todo["todo_id"], "DONE", verified=True)

    done = store.complete_todo(
        todo["todo_id"],
        evidence=[{"run_id": "ci-123", "status": "PASS"}],
        verification={"status": "PASS", "tests": 42},
    )
    assert done["status"] == "DONE"
    assert done["verified"] is True
    assert done["progress"] == 100
    assert done["evidence"]


def test_todo_dependencies_block_out_of_order_completion(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    first = store.add_todo(session_id, "Implement")
    second = store.add_todo(session_id, "Certify", dependencies=[first["todo_id"]])

    with pytest.raises(PermissionError, match="dependencies"):
        store.complete_todo(
            second["todo_id"],
            evidence=["run:premature"],
            verification={"status": "PASS"},
        )

    store.complete_todo(
        first["todo_id"],
        evidence=["run:implementation"],
        verification={"status": "PASS"},
    )
    done = store.complete_todo(
        second["todo_id"],
        evidence=["run:certification"],
        verification={"status": "VERIFIED"},
    )
    assert done["status"] == "DONE"


def test_plan_materializes_to_ordered_dependent_todos(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    plan = {
        "plan_fingerprint": "abc123",
        "steps": [
            {"description": "Inspect current state"},
            {"description": "Apply change"},
            {"description": "Verify change"},
        ],
    }

    todos = store.todos_from_plan(session_id, plan)
    assert [item["text"] for item in todos] == [
        "Inspect current state",
        "Apply change",
        "Verify change",
    ]
    assert [item["position"] for item in todos] == [1, 2, 3]
    assert todos[0]["dependencies"] == []
    assert todos[1]["dependencies"] == [todos[0]["todo_id"]]
    assert todos[2]["dependencies"] == [todos[1]["todo_id"]]
    assert all(item["plan_fingerprint"] == "abc123" for item in todos)


def test_todo_reopen_reorder_remove_and_progress(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    todo = store.add_todo(session_id, "Task", position=4, subagent_id="agent-review")

    running = store.update_todo(todo["todo_id"], "IN_PROGRESS", progress=45)
    assert running["progress"] == 45
    assert running["subagent_id"] == "agent-review"

    reordered = store.reorder_todo(todo["todo_id"], 1)
    assert reordered["position"] == 1

    completed = store.complete_todo(
        todo["todo_id"],
        evidence=["test:PASS"],
        verification={"status": "PASS"},
    )
    assert completed["verified"] is True

    reopened = store.reopen_todo(todo["todo_id"])
    assert reopened["status"] == "OPEN"
    assert reopened["verified"] is False
    assert reopened["progress"] == 0

    removed = store.remove_todo(todo["todo_id"])
    assert removed["removed"] is True


def test_todo_cannot_remove_dependency_used_by_another_task(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    first = store.add_todo(session_id, "Foundation")
    store.add_todo(session_id, "Dependent", dependencies=[first["todo_id"]])

    with pytest.raises(PermissionError, match="dependent tasks"):
        store.remove_todo(first["todo_id"])


def test_todo_tools_and_api_surface_include_verified_lifecycle():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "session_todo_add",
        "session_todo_update",
        "session_todo_complete",
        "session_todo_reopen",
        "session_todo_remove",
        "session_todo_reorder",
        "session_todo_dependencies",
        "session_todos_from_plan",
        "session_todos",
    } <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert {
        "todo-add",
        "todo-update",
        "todo-complete",
        "todo-reopen",
        "todo-remove",
        "todo-reorder",
        "todo-dependencies",
        "todos-from-plan",
        "todos",
    } <= set(sessions)
