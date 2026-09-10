from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app


def test_api_v1_runtime_resources_and_legacy_tool_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    client = TestClient(create_app())

    # Legacy generic tool route remains compatible.
    legacy = client.post(
        "/tools/reconcile_row_count",
        json={"args": {"source_value": 2, "target_value": 1}},
    )
    assert legacy.status_code == 200
    assert legacy.json()["status"] == "FAIL"

    created = client.post(
        "/api/v1/sessions",
        json={"title": "API parity session"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]

    message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "Review reservation lineage"},
    )
    assert message.status_code == 200, message.text

    todo = client.post(
        f"/api/v1/sessions/{session_id}/todos",
        json={"text": "verify CI", "priority": 10},
    )
    assert todo.status_code == 200, todo.text
    todo_id = todo.json()["todo_id"]

    projected = client.get(f"/api/v1/sessions/{session_id}")
    assert projected.status_code == 200
    assert projected.json()["role_counts"]["user"] == 1

    patched = client.patch(
        f"/api/v1/sessions/todos/{todo_id}",
        json={
            "status": "DONE",
            "verified": True,
            "evidence": [{"source": "api-v1-runtime-test", "status": "PASS"}],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "DONE"

    termination = client.get(f"/api/v1/sessions/{session_id}/termination")
    assert termination.status_code == 200
    assert termination.json()["can_terminate"] is True


def test_api_v1_memory_training_and_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    client = TestClient(create_app())

    saved = client.post(
        "/api/v1/memory",
        json={
            "content": "fact_reservation grain is reservation_id",
            "project_id": "hotel",
            "tags": ["reservation"],
        },
    )
    assert saved.status_code == 200, saved.text
    memory_id = saved.json()["memory_id"]

    found = client.get(
        "/api/v1/memory",
        params={"query": "reservation", "project_id": "hotel"},
    )
    assert found.status_code == 200
    assert found.json()["memories"][0]["memory_id"] == memory_id

    ingested = client.post(
        "/api/v1/training/ingest-text",
        json={
            "source": "docs/reservation.md",
            "text": "Reservation lineage uses reservation_id.",
        },
    )
    assert ingested.status_code == 200, ingested.text
    searched = client.get(
        "/api/v1/training/search",
        params={"query": "reservation lineage"},
    )
    assert searched.status_code == 200
    assert searched.json()["results"]

    catalog = client.get("/api/v1/skills/catalog")
    assert catalog.status_code == 200
    skill_names = {item["name"] for item in catalog.json()["skills"]}
    assert len(skill_names) == 32
    assert {
        "altimate-setup", "dbt-pr-review", "sql-review", "training-status",
        "airflow-analyze", "airflow-troubleshoot", "airflow-backfill",
        "airflow-upgrade", "airflow-security", "pipeline-health", "root-cause",
    }.issubset(skill_names)

    custom = client.post(
        "/api/v1/skills",
        json={
            "name": "api-skill",
            "description": "API test skill",
            "body": "Use deterministic evidence.",
        },
    )
    assert custom.status_code == 200, custom.text
    assert client.get("/api/v1/skills/api-skill/test").json()["status"] == "PASS"

    disabled = client.post("/api/v1/skills/api-skill/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    enabled = client.post("/api/v1/skills/api-skill/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True


def test_api_v1_provider_mcp_connection_and_metadata_surfaces(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    client = TestClient(create_app())

    providers = client.get("/api/v1/providers")
    assert providers.status_code == 200
    assert "providers" in providers.json()

    auth = client.get("/api/v1/providers/auth")
    assert auth.status_code == 200

    mcp = client.get("/api/v1/mcp")
    assert mcp.status_code == 200
    assert "servers" in mcp.json()

    catalog = client.get("/api/v1/mcp/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["entries"]

    discovered = client.get("/api/v1/mcp/discover")
    assert discovered.status_code == 200

    connections = client.get("/api/v1/connections")
    assert connections.status_code == 200
    assert connections.json()["connections"] == []

    added = client.post(
        "/api/v1/connections",
        json={"args": {"name": "local", "platform": "sqlite", "config": {"database": ":memory:"}}},
    )
    assert added.status_code == 200, added.text

    tested = client.post("/api/v1/connections/local/test")
    assert tested.status_code == 200
    assert tested.json()["status"] == "PASS"

    metadata = client.get("/api/v1/metadata/status")
    assert metadata.status_code == 200
    assert metadata.json()["objects"] == 0


def test_api_v1_jobs_reject_mutating_underlying_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    client = TestClient(create_app())

    denied = client.post(
        "/api/v1/jobs",
        json={"tool": "memory_save", "args": {"content": "nope"}},
    )
    assert denied.status_code == 403
    assert "refuse mutating tool" in denied.text
    assert denied.json()["detail"]["error_type"] == "PERMISSION_FAILURE"
