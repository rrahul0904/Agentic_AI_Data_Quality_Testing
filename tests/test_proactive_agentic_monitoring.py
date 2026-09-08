from __future__ import annotations

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.tools.builtin import build_tool_registry


def service(tmp_path):
    return SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        tmp_path / "project",
    )


def test_healthy_proactive_signal_does_not_create_incident(tmp_path):
    result = service(tmp_path).detect_and_investigate({
        "airflow_state": "SUCCESS",
        "dbt_state": "SUCCESS",
        "payment_to_reservation_ratio": 0.96,
        "historical_payment_to_reservation_ratio": 0.97,
        "ratio_tolerance": 0.1,
    })
    assert result["status"] == "PASS"
    assert result["incident_created"] is False


def test_green_orchestration_anomaly_automatically_creates_incident(tmp_path):
    result = service(tmp_path).detect_and_investigate({
        "airflow_state": "SUCCESS",
        "dbt_state": "SUCCESS",
        "payment_to_reservation_ratio": 0.79,
        "historical_payment_to_reservation_ratio": 0.97,
        "ratio_tolerance": 0.1,
    })
    assert result["status"] == "ANOMALY"
    assert result["incident_created"] is True
    investigation = result["investigation"]
    assert investigation["state"] == "AWAITING_APPROVAL"
    assert investigation["root_cause"] == "BUSINESS_COMPLETENESS_ANOMALY"
    assert investigation["first_divergence"] == "source→raw"


def test_store_migrates_pre_correlation_evidence_table(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE incident_evidence (
        evidence_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        tier INTEGER NOT NULL,
        kind TEXT NOT NULL,
        source TEXT NOT NULL,
        summary TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
        )"""
    )
    connection.commit()
    connection.close()

    migrated = InvestigationStore(path)
    columns = {
        row["name"]
        for row in migrated.connection.execute("PRAGMA table_info(incident_evidence)").fetchall()
    }
    assert "correlation_json" in columns
