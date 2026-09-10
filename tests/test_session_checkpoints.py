from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.session import SessionStore
from agentic_data_platform.tools.builtin import build_tool_registry


def test_session_history_is_durable_and_fingerprinted(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create(title="History")["session_id"]
    store.append_message(session_id, "user", "inspect pipeline")
    store.append_message(session_id, "assistant", "checking evidence")

    history = store.history(session_id)

    assert history["status"] == "PASS"
    assert history["message_count"] == 2
    assert [item["role"] for item in history["messages"]] == ["user", "assistant"]
    assert history["history_fingerprint"]


def test_checkpoint_captures_messages_todos_reminders_and_state(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create(title="Checkpoint")["session_id"]
    store.append_message(session_id, "user", "start")
    todo = store.add_todo(session_id, "verify pipeline", priority=10)
    store.add_reminder(session_id, "review evidence", {"type": "manual"})
    store.patch_state(session_id, {"phase": "investigation"})

    checkpoint = store.create_checkpoint(
        session_id,
        label="before-change",
        metadata={"reason": "baseline"},
    )

    assert checkpoint["snapshot_fingerprint"]
    assert checkpoint["label"] == "before-change"
    assert checkpoint["metadata"]["reason"] == "baseline"
    assert checkpoint["snapshot"]["messages"][0]["content"] == "start"
    assert checkpoint["snapshot"]["todos"][0]["todo_id"] == todo["todo_id"]
    assert checkpoint["snapshot"]["reminders"]
    assert checkpoint["snapshot"]["state"]["phase"] == "investigation"


def test_checkpoint_diff_reports_message_todo_state_and_status_changes(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    todo = store.add_todo(session_id, "implement")

    before = store.create_checkpoint(session_id, label="before")

    store.append_message(session_id, "assistant", "implementation complete")
    store.update_todo(todo["todo_id"], "IN_PROGRESS", progress=50)
    store.patch_state(session_id, {"phase": "verification"})
    store.set_status(session_id, "RUNNING")

    after = store.create_checkpoint(session_id, label="after")
    diff = store.checkpoint_diff(before["checkpoint_id"], after["checkpoint_id"])

    assert diff["status"] == "PASS"
    assert diff["messages"]["added"][0]["content"] == "implementation complete"
    assert diff["todos"]["changed"][0]["after"]["progress"] == 50
    assert diff["state_changes"][0]["key"] == "phase"
    assert diff["session_status"] == {"before": "IDLE", "after": "RUNNING"}
    assert diff["diff_fingerprint"]


def test_checkpoint_review_uses_latest_two_snapshots(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    store.create_checkpoint(session_id, label="one")
    store.append_message(session_id, "user", "second state")
    store.create_checkpoint(session_id, label="two")

    review = store.checkpoint_review(session_id)

    assert review["status"] == "PASS"
    assert review["latest_checkpoint"]["label"] == "two"
    assert review["previous_checkpoint"]["label"] == "one"
    assert review["diff"]["messages"]["added"][0]["content"] == "second state"
    assert review["review_fingerprint"]


def test_checkpoint_diff_rejects_cross_session_comparison(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    first = store.create()["session_id"]
    second = store.create()["session_id"]
    a = store.create_checkpoint(first)
    b = store.create_checkpoint(second)

    try:
        store.checkpoint_diff(a["checkpoint_id"], b["checkpoint_id"])
    except ValueError as exc:
        assert "same session" in str(exc)
    else:
        raise AssertionError("cross-session checkpoint diff should fail")


def test_checkpoint_delete_is_explicit_and_removes_only_one_snapshot(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session_id = store.create()["session_id"]
    first = store.create_checkpoint(session_id, label="one")
    second = store.create_checkpoint(session_id, label="two")

    removed = store.delete_checkpoint(first["checkpoint_id"])
    assert removed["removed"] is True
    remaining = store.checkpoints(session_id)
    assert [item["checkpoint_id"] for item in remaining] == [second["checkpoint_id"]]


def test_checkpoint_tools_and_rest_api_are_exposed(tmp_path, monkeypatch):
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "session_history",
        "session_checkpoint_create",
        "session_checkpoint_list",
        "session_checkpoint_show",
        "session_checkpoint_diff",
        "session_checkpoint_review",
        "session_checkpoint_delete",
    } <= names

    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    client = TestClient(create_app())
    session = client.post("/api/v1/sessions", json={"title": "Checkpoint API"})
    assert session.status_code == 200, session.text
    session_id = session.json()["session_id"]

    client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "baseline"},
    )
    first = client.post(
        f"/api/v1/sessions/{session_id}/checkpoints",
        json={"args": {"label": "before"}},
    )
    assert first.status_code == 200, first.text

    client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"role": "assistant", "content": "changed"},
    )
    second = client.post(
        f"/api/v1/sessions/{session_id}/checkpoints",
        json={"args": {"label": "after"}},
    )
    assert second.status_code == 200, second.text

    history = client.get(f"/api/v1/sessions/{session_id}/history")
    assert history.status_code == 200
    assert history.json()["message_count"] == 2

    diff = client.get(
        "/api/v1/session-checkpoint-diff",
        params={
            "from_checkpoint_id": first.json()["checkpoint_id"],
            "to_checkpoint_id": second.json()["checkpoint_id"],
        },
    )
    assert diff.status_code == 200
    assert diff.json()["messages"]["added"][0]["content"] == "changed"

    review = client.get(f"/api/v1/sessions/{session_id}/checkpoint-review")
    assert review.status_code == 200
    assert review.json()["diff_fingerprint"] if "diff_fingerprint" in review.json() else review.json()["diff"]["diff_fingerprint"]
