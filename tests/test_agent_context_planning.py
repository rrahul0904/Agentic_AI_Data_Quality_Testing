from __future__ import annotations

from pathlib import Path

from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.agents.roles import (
    AgentContext,
    BusinessContextAgent,
    ExecutionPlanningAgent,
)
from agentic_data_platform.agents.scenarios import get_scenario


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "hospitality-snowflake-data-platform"


def dummy_context(scenario_id: str):
    scenario = get_scenario(scenario_id)
    return AgentContext(
        scenario=scenario,
        incident_id="incident-test",
        project=PROJECT,
        invoke=lambda role, name, args: {},
        evidence=[],
        shared={},
    )


def test_airflow_job_catalog_exposes_real_load_strategy():
    inventory = AirflowProject.scan(PROJECT)
    assert inventory.details("28_postgres_payment_transaction_ingest")["load_strategy"] == "high_watermark"
    assert inventory.details("21_postgres_user_identity_ingest")["load_strategy"] == "timestamp_incremental"
    assert inventory.details("38_file_partner_bookings_ingest")["load_strategy"] == "file_manifest"


def test_business_context_maps_cross_system_assets():
    context = dummy_context("watermark_defect")
    result = BusinessContextAgent().run(context)
    assert result.observations["criticality"] == "P1"
    assert "postgres.payment_transaction" in result.observations["source_assets"]
    assert any("RAW" in item.upper() for item in result.observations["raw_assets"])
    assert "mart_payment_reconciliation" in result.observations["mart_assets"]


def test_execution_planner_changes_strategy_with_scale():
    context = dummy_context("watermark_defect")
    result = ExecutionPlanningAgent().run(context)
    assert result.observations["strategy"] == "bounded-row-count-reconciliation"

    base = get_scenario("watermark_defect")
    scaled = type(base)(
        **{
            **base.__dict__,
            "signals": {**base.signals, "row_estimate": 900_000_000},
        }
    )
    large = AgentContext(scaled, "incident-scale", PROJECT, lambda role, name, args: {}, [], {})
    large_result = ExecutionPlanningAgent().run(large)
    assert large_result.observations["strategy"] == "hierarchical-bucket-hashing"
