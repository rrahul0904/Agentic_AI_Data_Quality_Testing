from __future__ import annotations

from pathlib import Path

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.tools.builtin import build_tool_registry


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "hospitality-snowflake-data-platform"


def test_mapping_agent_persists_reusable_source_target_chain(tmp_path):
    store = InvestigationStore(tmp_path / "investigations.db")
    service = SupervisorAgent(build_tool_registry(), store, PROJECT)
    report = service.investigate("watermark_defect")
    mappings = store.mappings(report.incident_id)
    assert mappings
    assert mappings[0]["source"] == "postgres.payment_transaction"
    assert mappings[0]["target"] == "airflow.28_postgres_payment_transaction_ingest"
    assert any(item["target"] == "stg_postgres_payment_transaction" for item in mappings)


def test_transformation_agent_reads_dbt_artifact_intelligence(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        PROJECT,
    )
    report = service.investigate("incremental_predicate_defect")
    transformation = next(
        item for item in report.agent_results
        if item.role.value == "transformation"
    )
    assert "dbt_incremental_analysis" in transformation.tools_used
    assert "incremental_models" in transformation.observations
    names = {item.get("name") for item in transformation.observations["incremental_models"]}
    assert "fact_payment" in names
