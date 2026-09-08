from __future__ import annotations

import pytest

from agentic_data_platform.agents import (
    EvidenceRecord,
    InvestigationStore,
    SupervisorAgent,
)
from agentic_data_platform.tools.builtin import build_tool_registry


def test_evidence_store_rejects_overwrite(tmp_path):
    store = InvestigationStore(tmp_path / "investigations.db")
    incident_id = store.create_incident(
        "watermark_defect",
        "test",
        "mart_payment_reconciliation",
        {"detected": True},
    )
    evidence = EvidenceRecord(
        kind="measurement",
        source="test",
        summary="immutable measurement",
        payload={"count": 10},
    )
    store.save_evidence(incident_id, evidence)
    with pytest.raises(ValueError, match="immutable evidence already exists"):
        store.save_evidence(incident_id, evidence)
    assert store.evidence(incident_id)[0]["payload"] == {"count": 10}


def test_quality_agent_proposes_context_aware_rules_without_applying_them(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        tmp_path / "project",
    )
    report = service.investigate("watermark_defect")
    quality = next(item for item in report.agent_results if item.role.value == "quality")
    checks = {item["check_type"] for item in quality.observations["proposed_tests"]}
    assert {"row_count", "freshness", "not_null", "unique"} <= checks
    assert all(item["status"] == "PROPOSED" for item in quality.observations["proposed_tests"])
    assert all(item["applied"] is False for item in quality.observations["proposed_tests"])
