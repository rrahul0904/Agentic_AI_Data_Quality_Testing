"""Deterministic root-cause trust policy.

LLMs may synthesize these results, but they cannot relax the execution-boundary
or evidence-precedence rules implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from agentic_data_platform.agents.contracts import (
    DiagnosticLayer,
    ExecutionLifecycleEvidence,
    Finding,
    FindingClassification,
    FirstDivergence,
)


EVIDENCE_WEIGHTS: dict[str, float] = {
    "direct_execution": 1.00,
    "runtime_state": 0.92,
    "task_process_log": 0.86,
    "orchestrator_metadata": 0.76,
    "dependency_response": 0.68,
    "data_state": 0.55,
    "static_analysis": 0.35,
    "llm_inference": 0.15,
}


@dataclass(frozen=True)
class ExecutionBoundaryDecision:
    execution_boundary_crossed: bool
    runtime_start_proven: bool
    operator_start_proven: bool
    application_root_cause_allowed: bool
    dependency_root_cause_allowed: bool
    reason: str

    def public(self) -> dict[str, Any]:
        return {
            "execution_boundary_crossed": self.execution_boundary_crossed,
            "runtime_start_proven": self.runtime_start_proven,
            "operator_start_proven": self.operator_start_proven,
            "application_root_cause_allowed": self.application_root_cause_allowed,
            "dependency_root_cause_allowed": self.dependency_root_cause_allowed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TrustCoreEvaluation:
    root_cause: str | None
    confidence: float
    lifecycle: ExecutionLifecycleEvidence | None
    boundary: ExecutionBoundaryDecision | None
    first_divergence: FirstDivergence | None
    findings: tuple[Finding, ...]


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _state(value: Any) -> str | None:
    return str(value).upper() if _present(value) else None


def _duration_seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return None


def normalize_execution_lifecycle(
    signals: dict[str, Any],
    evidence_ids: Iterable[str] = (),
) -> ExecutionLifecycleEvidence | None:
    """Normalize connector/scenario fields without inventing missing transitions."""
    task_id = signals.get("task_id")
    run_id = signals.get("run_id") or signals.get("dag_run_id")
    lifecycle_keys = {
        "metadata_state", "executor_state", "queued_at", "running_at", "operator_started_at",
        "runtime_start_proven", "operator_start_proven", "task_log_exists",
    }
    if not task_id and not run_id and not lifecycle_keys.intersection(signals):
        return None
    queued_at = signals.get("queued_at")
    ended_at = signals.get("ended_at") or signals.get("failed_at") or signals.get("end_date")
    queued_duration = signals.get("queued_duration_seconds")
    if queued_duration is None:
        queued_duration = _duration_seconds(queued_at, ended_at)
    running_at = signals.get("running_at") or signals.get("start_date")
    operator_started_at = signals.get("operator_started_at")
    return ExecutionLifecycleEvidence(
        task_id=str(task_id or "unknown-task"),
        run_id=str(run_id or "unknown-run"),
        dag_id=str(signals["dag_id"]) if _present(signals.get("dag_id")) else None,
        created_at=signals.get("created_at"),
        scheduled_at=signals.get("scheduled_at"),
        queued_at=queued_at,
        executor_accepted_at=signals.get("executor_accepted_at"),
        process_created_at=signals.get("process_created_at"),
        running_at=running_at,
        operator_started_at=operator_started_at,
        first_external_call_at=signals.get("first_external_call_at"),
        ended_at=ended_at,
        metadata_state=_state(signals.get("metadata_state") or signals.get("task_state")),
        executor_state=_state(signals.get("executor_state")),
        task_log_exists=signals.get("task_log_exists"),
        operator_start_proven=bool(signals.get("operator_start_proven") or operator_started_at),
        runtime_start_proven=bool(signals.get("runtime_start_proven") or running_at),
        try_number=signals.get("try_number") or signals.get("task_try_number"),
        mapped_task_index=signals.get("mapped_task_index"),
        pool=signals.get("pool"),
        queue=signals.get("queue"),
        priority=signals.get("priority"),
        executor=signals.get("executor"),
        parallelism=signals.get("parallelism"),
        queued_duration_seconds=float(queued_duration) if queued_duration is not None else None,
        evidence_ids=tuple(evidence_ids),
    )


def execution_boundary_gate(lifecycle: ExecutionLifecycleEvidence) -> ExecutionBoundaryDecision:
    runtime = bool(lifecycle.runtime_start_proven or lifecycle.running_at)
    operator = bool(lifecycle.operator_start_proven or lifecycle.operator_started_at)
    crossed = runtime
    if not runtime:
        reason = "Task execution was not proven; application and dependency causes are prohibited."
    elif not operator:
        reason = "Runtime start was observed, but operator/user-code start was not proven."
    else:
        reason = "Runtime and operator/user-code execution were proven by evidence."
    return ExecutionBoundaryDecision(
        execution_boundary_crossed=crossed,
        runtime_start_proven=runtime,
        operator_start_proven=operator,
        application_root_cause_allowed=operator,
        dependency_root_cause_allowed=operator and bool(lifecycle.first_external_call_at),
        reason=reason,
    )


def _finding(
    title: str,
    description: str,
    classification: FindingClassification,
    domain: str,
    confidence: float,
    evidence_ids: tuple[str, ...],
    relationship: str,
) -> Finding:
    return Finding(title, description, classification, domain, confidence, evidence_ids, relationship)


def _queue_launch_evaluation(
    lifecycle: ExecutionLifecycleEvidence,
    evidence_ids: tuple[str, ...],
    signals: dict[str, Any],
) -> TrustCoreEvaluation:
    boundary = execution_boundary_gate(lifecycle)
    state_mismatch = lifecycle.metadata_state == "QUEUED" and lifecycle.executor_state in {"FAILED", "ERROR"}
    failed_without_running = (
        not boundary.runtime_start_proven
        and bool(lifecycle.queued_at or lifecycle.metadata_state == "QUEUED")
        and lifecycle.metadata_state in {"QUEUED", "FAILED", "UPSTREAM_FAILED"}
        and (lifecycle.executor_state in {"FAILED", "ERROR"} or _state(signals.get("task_state")) == "FAILED")
    )
    if not (state_mismatch or failed_without_running):
        return TrustCoreEvaluation(None, 0.0, lifecycle, boundary, None, ())

    confidence = 0.76
    if state_mismatch:
        confidence += 0.08
    if lifecycle.task_log_exists is False:
        confidence += 0.05
    if (lifecycle.queued_duration_seconds or 0) >= float(signals.get("task_queued_timeout_seconds") or 600):
        confidence += 0.05
    if int(signals.get("failed_sibling_count") or 0) >= 2:
        confidence += 0.04
    confidence = min(confidence, 0.98)
    divergence = FirstDivergence(
        DiagnosticLayer.ORCHESTRATOR_LIFECYCLE,
        str(lifecycle.executor or "Airflow scheduler/executor"),
        "QUEUED → RUNNING",
        f"{lifecycle.metadata_state or 'QUEUED'} → {lifecycle.executor_state or 'FAILED'}; RUNNING not observed",
        lifecycle.ended_at,
        evidence_ids,
        confidence,
        True,
    )
    findings = [
        _finding(
            "Airflow task-launch or queued-task-timeout failure",
            "The task did not cross the QUEUED → RUNNING execution boundary.",
            FindingClassification.PROBABLE_ROOT_CAUSE,
            "airflow",
            confidence,
            evidence_ids,
            "Earliest proven divergence for this execution.",
        )
    ]
    if signals.get("watermark_missing") or signals.get("missing_watermark_rows"):
        findings.append(_finding(
            "Missing ingestion watermark initialization",
            "No matching CONTROL.INGESTION_WATERMARKS record was observed.",
            FindingClassification.LATENT_DEFECT,
            "snowflake",
            0.88,
            evidence_ids,
            "Potential next failure, but not proven to have executed during this run.",
        ))
    if signals.get("target_row_count") == 0:
        findings.append(_finding(
            "Target remained empty",
            "The target contains no rows after the failed orchestration attempt.",
            FindingClassification.CONSEQUENCE,
            "snowflake",
            0.95,
            evidence_ids,
            "Downstream consequence of the task not starting.",
        ))
    return TrustCoreEvaluation(
        "AIRFLOW_TASK_LAUNCH_FAILURE", confidence, lifecycle, boundary, divergence, tuple(findings)
    )


def evaluate_runtime_rca(
    signals: dict[str, Any],
    evidence_ids: Iterable[str] = (),
) -> TrustCoreEvaluation:
    """Evaluate the earliest proven runtime failure with hard boundary guardrails."""
    ids = tuple(evidence_ids)
    lifecycle = normalize_execution_lifecycle(signals, ids)
    if lifecycle is not None:
        queue_result = _queue_launch_evaluation(lifecycle, ids, signals)
        if queue_result.root_cause:
            return queue_result
        boundary = execution_boundary_gate(lifecycle)
    else:
        boundary = None

    def result(name: str, confidence: float, layer: DiagnosticLayer, component: str, expected: str,
               observed: str, title: str, domain: str) -> TrustCoreEvaluation:
        divergence = FirstDivergence(layer, component, expected, observed, signals.get("ended_at"), ids, confidence, True)
        finding = _finding(title, observed, FindingClassification.PROBABLE_ROOT_CAUSE, domain, confidence, ids,
                           "Earliest proven divergence for this execution.")
        return TrustCoreEvaluation(name, confidence, lifecycle, boundary, divergence, (finding,))

    operator_allowed = boundary.application_root_cause_allowed if boundary else bool(signals.get("operator_start_proven"))
    if operator_allowed and (signals.get("python_traceback") or signals.get("application_exception")):
        return result("APPLICATION_CODE_EXCEPTION", 0.96, DiagnosticLayer.APPLICATION_CODE,
                      "Airflow operator", "Operator completes", str(signals.get("python_traceback") or signals.get("application_exception")),
                      "Application/operator exception", "application")
    if operator_allowed and signals.get("postgres_connection_attempted") and signals.get("postgres_error"):
        return result("POSTGRES_SOURCE_CONNECTIVITY_FAILURE", 0.96, DiagnosticLayer.SOURCE_CONNECTIVITY,
                      "PostgreSQL", "Connection succeeds", str(signals["postgres_error"]),
                      "PostgreSQL source connectivity failure", "postgres")
    if operator_allowed and signals.get("snowflake_load_attempted") and signals.get("snowflake_error"):
        return result("SNOWFLAKE_TARGET_LOAD_FAILURE", 0.96, DiagnosticLayer.TARGET_LOAD,
                      "Snowflake load", "COPY/INSERT succeeds", str(signals["snowflake_error"]),
                      "Snowflake target/load failure", "snowflake")
    if signals.get("dbt_invocation_started") and signals.get("compiled_sql_executed") and signals.get("warehouse_error"):
        return result("DBT_TRANSFORMATION_FAILURE", 0.96, DiagnosticLayer.TRANSFORMATION,
                      str(signals.get("dbt_model") or "dbt model"), "Compiled SQL succeeds", str(signals["warehouse_error"]),
                      "dbt transformation failure", "dbt")
    if signals.get("airflow_state") == "SUCCESS" and signals.get("dbt_state") == "SUCCESS" and signals.get("dq_failed"):
        return result("DATA_QUALITY_FAILURE", 0.94, DiagnosticLayer.DATA_QUALITY,
                      str(signals.get("dq_check") or "data-quality check"), "Quality check passes", "Quality check failed",
                      "Data-quality failure after successful orchestration", "quality")
    return TrustCoreEvaluation(None, 0.0, lifecycle, boundary, None, ())


_PAIR_LAYERS: tuple[tuple[str, DiagnosticLayer], ...] = (
    ("cert", DiagnosticLayer.CERTIFICATION),
    ("recon", DiagnosticLayer.RECONCILIATION),
    ("quality", DiagnosticLayer.DATA_QUALITY),
    ("test", DiagnosticLayer.DATA_QUALITY),
    ("mart", DiagnosticLayer.CONSUMPTION),
    ("core", DiagnosticLayer.TRANSFORMATION),
    ("intermediate", DiagnosticLayer.TRANSFORMATION),
    ("staging", DiagnosticLayer.TRANSFORMATION),
    ("raw", DiagnosticLayer.TARGET_LOAD),
    ("extract", DiagnosticLayer.EXTRACTION),
    ("source", DiagnosticLayer.SOURCE_CONNECTIVITY),
)


def divergence_from_comparisons(
    comparisons: Iterable[dict[str, Any]],
    evidence_ids: Iterable[str] = (),
) -> FirstDivergence | None:
    for item in comparisons:
        if str(item.get("status")).upper() != "FAIL":
            continue
        pair = str(item.get("pair") or "unknown boundary")
        folded = pair.casefold()
        layer = next((candidate for token, candidate in _PAIR_LAYERS if token in folded), DiagnosticLayer.RECONCILIATION)
        return FirstDivergence(
            layer, pair, "Boundary values reconcile", "Boundary comparison failed",
            item.get("timestamp"), tuple(evidence_ids), 0.90, True,
        )
    return None
