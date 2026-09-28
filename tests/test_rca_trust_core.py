from __future__ import annotations

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.agents.rca_policy import (
    EVIDENCE_WEIGHTS,
    evaluate_runtime_rca,
    execution_boundary_gate,
    normalize_execution_lifecycle,
)
from agentic_data_platform.tools.builtin import build_tool_registry


def queued_failure() -> dict:
    return {
        "dag_id": "ingest_reference_data",
        "run_id": "manual__2026-09-09T22:33:41+00:00",
        "task_id": "load_properties.determine_window",
        "metadata_state": "QUEUED",
        "executor_state": "FAILED",
        "queued_at": "2026-09-09T22:33:41+00:00",
        "failed_at": "2026-09-09T22:43:51+00:00",
        "queued_duration_seconds": 610,
        "task_queued_timeout_seconds": 600,
        "runtime_start_proven": False,
        "operator_start_proven": False,
        "task_log_exists": False,
        "executor": "LocalExecutor",
        "parallelism": 32,
        "failed_sibling_count": 6,
        "watermark_missing": True,
        "target_row_count": 0,
    }


def test_evidence_precedence_is_explicit_and_monotonic():
    assert list(EVIDENCE_WEIGHTS) == [
        "direct_execution",
        "runtime_state",
        "task_process_log",
        "orchestrator_metadata",
        "dependency_response",
        "data_state",
        "static_analysis",
        "llm_inference",
    ]
    assert list(EVIDENCE_WEIGHTS.values()) == sorted(EVIDENCE_WEIGHTS.values(), reverse=True)


def test_execution_boundary_prohibits_application_rca_without_runtime_start():
    lifecycle = normalize_execution_lifecycle(queued_failure(), ["ev-executor", "ev-metadata"])
    assert lifecycle is not None
    decision = execution_boundary_gate(lifecycle)
    assert decision.execution_boundary_crossed is False
    assert decision.application_root_cause_allowed is False
    assert decision.dependency_root_cause_allowed is False


def test_golden_queued_task_failure_keeps_watermark_latent():
    result = evaluate_runtime_rca(queued_failure(), ["ev-executor", "ev-metadata", "ev-watermark"])
    assert result.root_cause == "AIRFLOW_TASK_LAUNCH_FAILURE"
    assert result.first_divergence is not None
    assert result.first_divergence.layer.value == "L1_ORCHESTRATOR_LIFECYCLE"
    assert result.first_divergence.expected_state == "QUEUED → RUNNING"
    by_class = {item.classification.value: item for item in result.findings}
    assert by_class["PROBABLE_ROOT_CAUSE"].domain == "airflow"
    assert by_class["LATENT_DEFECT"].domain == "snowflake"
    assert "not proven" in by_class["LATENT_DEFECT"].relationship.casefold()
    assert all("WATERMARK" not in item.title.upper() for item in result.findings if item.classification.value == "PROBABLE_ROOT_CAUSE")


def test_application_exception_requires_operator_start():
    blocked = evaluate_runtime_rca({
        **queued_failure(),
        "python_traceback": "ValueError: bad watermark",
    })
    assert blocked.root_cause == "AIRFLOW_TASK_LAUNCH_FAILURE"

    allowed = evaluate_runtime_rca({
        "dag_id": "demo", "run_id": "run-1", "task_id": "transform",
        "metadata_state": "FAILED", "running_at": "2026-09-09T22:34:00+00:00",
        "operator_started_at": "2026-09-09T22:34:01+00:00",
        "runtime_start_proven": True, "operator_start_proven": True,
        "python_traceback": "ValueError: invalid business rule",
    })
    assert allowed.root_cause == "APPLICATION_CODE_EXCEPTION"
    assert allowed.first_divergence.layer.value == "L3_APPLICATION_OPERATOR_CODE"


def test_dependency_and_quality_boundaries():
    postgres = evaluate_runtime_rca({
        "task_id": "extract", "run_id": "run-2", "running_at": "2026-09-09T22:34:00+00:00",
        "operator_started_at": "2026-09-09T22:34:01+00:00", "operator_start_proven": True,
        "postgres_connection_attempted": True, "postgres_error": "authentication failed",
    })
    assert postgres.root_cause == "POSTGRES_SOURCE_CONNECTIVITY_FAILURE"
    assert postgres.first_divergence.layer.value == "L4_SOURCE_CONNECTIVITY"

    snowflake = evaluate_runtime_rca({
        "task_id": "load", "run_id": "run-3", "running_at": "2026-09-09T22:34:00+00:00",
        "operator_started_at": "2026-09-09T22:34:01+00:00", "operator_start_proven": True,
        "snowflake_load_attempted": True, "snowflake_error": "COPY failed",
    })
    assert snowflake.root_cause == "SNOWFLAKE_TARGET_LOAD_FAILURE"
    assert snowflake.first_divergence.layer.value == "L7_TARGET_LOAD"

    dbt = evaluate_runtime_rca({
        "dbt_invocation_started": True, "compiled_sql_executed": True,
        "dbt_model": "fct_reservations", "warehouse_error": "invalid identifier",
    })
    assert dbt.root_cause == "DBT_TRANSFORMATION_FAILURE"

    dq = evaluate_runtime_rca({
        "airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "dq_failed": True,
        "dq_check": "reservation freshness",
    })
    assert dq.root_cause == "DATA_QUALITY_FAILURE"
    assert dq.first_divergence.layer.value == "L8_DATA_QUALITY"


def test_golden_investigation_persists_structured_reasoning(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        tmp_path / "project",
    )
    report = service.investigate(
        "airflow_queued_task_timeout",
        question="Why did ingest_reference_data fail?",
    )
    public = service.public_report(report.incident_id)
    assert public["question"] == "Why did ingest_reference_data fail?"
    assert public["root_cause"] == "AIRFLOW_TASK_LAUNCH_FAILURE"
    assert public["structured_first_divergence"]["layer"] == "L1_ORCHESTRATOR_LIFECYCLE"
    assert public["execution_lifecycles"][0]["runtime_start_proven"] is False
    classes = {item["classification"] for item in public["findings"]}
    assert {"PROBABLE_ROOT_CAUSE", "LATENT_DEFECT", "CONSEQUENCE"} <= classes
