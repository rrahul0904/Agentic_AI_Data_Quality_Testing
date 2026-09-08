from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository


ROOT = Path(__file__).resolve().parents[2]
HOSPITALITY = ROOT / "hospitality-snowflake-data-platform"


def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(HOSPITALITY))
    monkeypatch.setenv("ADE_INVESTIGATION_DATABASE", str(tmp_path / "investigations.db"))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    repository = SQLiteControlPlaneRepository(tmp_path / "repo.db")
    return TestClient(create_app(repository))


def test_agentic_roster_and_scenarios_are_first_class_api_resources(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    roster = api.get("/api/v1/agents/roster")
    assert roster.status_code == 200
    assert roster.json()["count"] == 12
    roles = {item["role"] for item in roster.json()["agents"]}
    assert roles == {
        "supervisor",
        "metadata",
        "business_context",
        "lineage",
        "transformation",
        "mapping",
        "quality",
        "execution_planning",
        "evidence",
        "rca",
        "impact",
        "remediation",
    }

    scenarios = api.get("/api/v1/investigations/scenarios")
    assert scenarios.status_code == 200
    assert scenarios.json()["count"] == 18
    assert "airflow_green_data_bad" in {
        item["scenario_id"] for item in scenarios.json()["scenarios"]
    }


def test_full_investigation_requires_approval_then_resolves(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    started = api.post("/api/v1/investigations/watermark_defect/start", json={})
    assert started.status_code == 200
    pending = started.json()
    assert pending["state"] == "AWAITING_APPROVAL"
    assert pending["first_divergence"] == "source→raw"
    assert pending["root_cause"] == "WATERMARK_ADVANCED_BEYOND_EXTRACT"
    assert pending["certification"] == "FAILED"
    assert pending["approved"] is False
    assert len(pending["evidence"]) >= 2
    assert any(item["status"] == "SUPPORTED" for item in pending["hypotheses"])

    incident_id = pending["incident_id"]
    forbidden = api.post(f"/api/v1/investigations/{incident_id}/execute", json={})
    assert forbidden.status_code == 403

    approval = api.post(
        f"/api/v1/investigations/{incident_id}/approve",
        json={"approved_by": "integration-test"},
    )
    assert approval.status_code == 200
    assert approval.json()["approved"] is True

    executed = api.post(f"/api/v1/investigations/{incident_id}/execute", json={})
    assert executed.status_code == 200
    resolved = executed.json()
    assert resolved["state"] == "RESOLVED"
    assert resolved["approved"] is True
    assert resolved["verification_result"]["status"] == "PASS"
    assert resolved["certification"] == "CERTIFIED"


def test_dbt_failure_dynamically_invokes_transformation_agent(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    response = api.post("/api/v1/investigations/dbt_filter_defect/start", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["root_cause"] == "DBT_FILTER_EXCLUDES_VALID_STATUS"
    assert payload["first_divergence"] == "staging→intermediate"
    roles = [item["role"] for item in payload["agent_results"]]
    assert "transformation" in roles


def test_source_to_raw_failure_skips_unnecessary_transformation_agent(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    response = api.post("/api/v1/investigations/watermark_defect/start", json={})
    assert response.status_code == 200
    roles = [item["role"] for item in response.json()["agent_results"]]
    assert "transformation" not in roles
    assert "supervisor" in roles
    assert "rca" in roles
    assert "impact" in roles
    assert "remediation" in roles
