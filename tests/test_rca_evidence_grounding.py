from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agentic_data_platform.agents.contracts import EvidenceRecord, EvidenceTier
from agentic_data_platform.agents.roles import AgentContext, RCAAgent
from agentic_data_platform.agents.scenarios import get_scenario


def test_rca_uses_persisted_evidence_not_scenario_signal_fields(tmp_path):
    runtime = get_scenario("watermark_defect").runtime_input()
    runtime_without_signals = replace(runtime, signals={})
    evidence = [
        EvidenceRecord(
            kind="reconciliation",
            source="source→raw",
            summary="source to raw mismatch",
            payload={
                "pair": "source→raw",
                "status": "FAIL",
                "source_count": 1_250_004,
                "target_count": 1_247_831,
            },
            tier=EvidenceTier.DIRECT_MEASUREMENT,
        ),
        EvidenceRecord(
            kind="runtime_state",
            source="airflow/dbt",
            summary="runtime evidence",
            payload={
                "airflow_state": "SUCCESS",
                "dbt_state": "SUCCESS",
                "extracted_max_timestamp": "2026-09-07T21:46:13+00:00",
                "persisted_watermark": "2026-09-07T23:59:59+00:00",
            },
            tier=EvidenceTier.RUNTIME_METADATA,
        ),
    ]
    context = AgentContext(
        runtime_without_signals,
        "incident-evidence-only",
        Path(tmp_path),
        lambda role, name, args: {},
        evidence,
        {},
    )
    result, hypotheses = RCAAgent().run(context)
    assert result.status == "DIAGNOSED"
    assert result.claim == "WATERMARK_ADVANCED_BEYOND_EXTRACT"
    assert result.observations["first_divergence"] == "source→raw"
    supported = [item for item in hypotheses if item.status.value == "SUPPORTED"]
    assert [item.name for item in supported] == ["WATERMARK_ADVANCED_BEYOND_EXTRACT"]


def test_rca_does_not_diagnose_without_persisted_evidence(tmp_path):
    runtime = get_scenario("watermark_defect").runtime_input()
    context = AgentContext(
        runtime,
        "incident-no-evidence",
        Path(tmp_path),
        lambda role, name, args: {},
        [],
        {},
    )
    result, _ = RCAAgent().run(context)
    assert result.status == "UNVERIFIED"
    assert result.claim == "INSUFFICIENT_EVIDENCE"
