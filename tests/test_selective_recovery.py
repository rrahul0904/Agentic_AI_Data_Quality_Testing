from __future__ import annotations

from agentic_data_platform.agents import (
    InvestigationStore,
    SupervisorAgent,
    build_selective_recovery_plan,
    get_scenario,
)
from agentic_data_platform.tools.builtin import build_tool_registry


def test_watermark_recovery_is_bounded_and_selective():
    scenario = get_scenario("watermark_defect")
    plan = build_selective_recovery_plan(scenario, scenario.downstream_assets)
    assert plan.bounded is True
    assert len(plan.airflow_actions) == 1
    action = plan.airflow_actions[0]
    assert action.target == "28_postgres_payment_transaction_ingest"
    assert action.operation == "bounded_backfill"
    assert action.arguments["start"] == "2026-09-07T21:46:13+00:00"
    assert action.arguments["end"] == "2026-09-07T23:59:59+00:00"
    assert action.arguments["reset_watermark"] is True
    assert plan.dbt_selector == "stg_postgres_payment_transaction+"
    assert plan.dbt_command == "dbt build --select stg_postgres_payment_transaction+"


def test_dbt_failure_uses_selective_downstream_build():
    scenario = get_scenario("dbt_filter_defect")
    plan = build_selective_recovery_plan(scenario, scenario.downstream_assets)
    assert plan.airflow_actions == ()
    assert plan.dbt_selector == "stg_orders+"
    assert plan.dbt_command == "dbt build --select stg_orders+"


def test_approved_execution_persists_selective_plan(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        tmp_path / "project",
    )
    pending = service.investigate("watermark_defect")
    service.approve(pending.incident_id, approved_by="operator")
    resolved = service.execute_approved(pending.incident_id)
    assert resolved.execution_result["dbt_selector"] == "stg_postgres_payment_transaction+"
    assert resolved.execution_result["airflow_actions"][0]["operation"] == "bounded_backfill"
    assert resolved.verification_result["status"] == "PASS"
    assert resolved.certification == "CERTIFIED"
