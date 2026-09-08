from __future__ import annotations

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.tools.builtin import build_tool_registry


def test_incident_certification_changes_only_after_all_verification_gates(tmp_path):
    store = InvestigationStore(tmp_path / "investigations.db")
    service = SupervisorAgent(build_tool_registry(), store, tmp_path / "project")
    pending = service.investigate("watermark_defect")

    before = store.latest_certifications(pending.incident_id)
    assert before == [
        {
            **before[0],
            "asset": "mart_payment_reconciliation",
            "status": "FAILED",
        }
    ]
    assert before[0]["reason"].startswith("Deterministic quality/anomaly gate failed")

    service.approve(pending.incident_id, approved_by="operator")
    resolved = service.execute_approved(pending.incident_id)
    after = store.latest_certifications(resolved.incident_id)
    certified = {item["asset"]: item["status"] for item in after}
    assert certified["mart_payment_reconciliation"] == "CERTIFIED"
    assert certified["fact_payment"] == "CERTIFIED"
    assert certified["int_payment_lifecycle"] == "CERTIFIED"
    assert all(item["evidence_ids"] for item in after if item["status"] == "CERTIFIED")
