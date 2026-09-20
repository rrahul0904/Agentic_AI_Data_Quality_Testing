from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository


ANALYST_TOKEN = "analyst-token-1234567890-abcdef"
BUILDER_TOKEN = "builder-token-1234567890-abcdef"
ADMIN_TOKEN = "admin-token-123456789012-abcdef"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _configure_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADE_RUNTIME_MODE", "production")
    monkeypatch.setenv("ADE_DEMO_MODE", "false")
    monkeypatch.setenv("ADE_AUTH_MODE", "api_key")
    monkeypatch.setenv(
        "ADE_API_KEYS_JSON",
        json.dumps(
            {
                "analyst": {
                    "token": ANALYST_TOKEN,
                    "subject": "analyst@example.test",
                    "role": "analyst",
                },
                "builder": {
                    "token": BUILDER_TOKEN,
                    "subject": "builder@example.test",
                    "role": "builder",
                },
                "admin": {
                    "token": ADMIN_TOKEN,
                    "subject": "admin@example.test",
                    "role": "admin",
                },
            }
        ),
    )


def test_production_runtime_refuses_demo_or_missing_auth(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ADE_RUNTIME_MODE", "production")
    monkeypatch.setenv("ADE_DEMO_MODE", "true")
    monkeypatch.setenv("ADE_AUTH_MODE", "disabled")
    monkeypatch.delenv("ADE_API_KEYS_JSON", raising=False)
    with pytest.raises(RuntimeError, match="ADE_DEMO_MODE=false"):
        create_app(SQLiteControlPlaneRepository(tmp_path / "bad.db"))


def test_production_authentication_and_actor_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _configure_production(monkeypatch)
    client = TestClient(create_app(SQLiteControlPlaneRepository(tmp_path / "auth.db")))

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/domains").status_code == 401
    assert client.get("/api/v1/domains", headers=_auth(ANALYST_TOKEN)).status_code == 200

    escalated = client.post(
        "/api/v1/dbt-next/agents-schema",
        headers=_auth(ANALYST_TOKEN),
        json={"args": {}, "actor_mode": "admin"},
    )
    assert escalated.status_code == 403
    assert "cannot assume admin" in escalated.text

    allowed = client.post(
        "/api/v1/dbt-next/agents-schema",
        headers=_auth(ANALYST_TOKEN),
        json={"args": {}, "actor_mode": "analyst"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["schema_version"] == "ade-agents/1.0"


def test_production_mutation_requires_server_approval(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _configure_production(monkeypatch)
    repo = SQLiteControlPlaneRepository(tmp_path / "approval.db")
    client = TestClient(create_app(repo))

    run = client.post(
        "/runs",
        headers=_auth(BUILDER_TOKEN),
        json={
            "project_id": "project-prod",
            "environment_id": "environment-prod",
            "intent": "production state execution",
        },
    )
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    builder_approval = client.post(
        "/approvals",
        headers=_auth(BUILDER_TOKEN),
        json={
            "run_id": run_id,
            "approved_by": "spoofed@example.test",
            "scope": "dbt_next_state_execute",
            "environment": "prod",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    assert builder_approval.status_code == 403

    self_approved = client.post(
        "/api/v1/dbt-next/state-execute",
        headers=_auth(BUILDER_TOKEN),
        json={
            "args": {
                "plan": {
                    "fingerprint": "plan-prod",
                    "selectors": {"build": [], "clone": [], "defer": [], "skip": []},
                    "actions": [],
                },
                "project_dir": str(tmp_path),
                "dry_run": True,
            },
            "actor_mode": "builder",
            "environment": "prod",
            "run_id": run_id,
            "approved": True,
        },
    )
    assert self_approved.status_code == 403
    assert "not trusted" in self_approved.text

    approval = client.post(
        "/approvals",
        headers=_auth(ADMIN_TOKEN),
        json={
            "run_id": run_id,
            "approved_by": "spoofed@example.test",
            "scope": "dbt_next_state_execute",
            "environment": "prod",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["approved_by"] == "admin@example.test"
    approval_id = approval_payload["approval_id"]

    request = {
        "args": {
            "plan": {
                "fingerprint": "plan-prod",
                "selectors": {"build": [], "clone": [], "defer": [], "skip": []},
                "actions": [],
            },
            "project_dir": str(tmp_path),
            "dry_run": True,
        },
        "actor_mode": "builder",
        "environment": "prod",
        "run_id": run_id,
        "approval_id": approval_id,
    }
    executed = client.post(
        "/api/v1/dbt-next/state-execute",
        headers=_auth(BUILDER_TOKEN),
        json=request,
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "DRY_RUN"

    consumed = repo.get_approval(approval_id)
    assert consumed is not None
    assert consumed["used_at"]

    replay = client.post(
        "/api/v1/dbt-next/state-execute",
        headers=_auth(BUILDER_TOKEN),
        json=request,
    )
    assert replay.status_code == 403
    assert "already consumed" in replay.text
