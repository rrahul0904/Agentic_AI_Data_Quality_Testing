"""Static and fixture-backed Airflow operational intelligence."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agentic_data_platform.platform.airflow import AirflowProject


def retry_analysis(project: str | Path) -> dict[str, Any]:
    inventory = AirflowProject.scan(project)
    missing = sorted(dag.dag_id for dag in inventory.dags.values() if not dag.retries)
    configured = sorted(dag.dag_id for dag in inventory.dags.values() if dag.retries and dag.retries > 0)
    return {
        "mode": "STATIC",
        "dag_count": len(inventory.dags),
        "configured_count": len(configured),
        "missing_or_zero_count": len(missing),
        "missing_or_zero": missing,
        "status": "WARN" if missing else "PASS",
    }


def schedule_analysis(project: str | Path) -> dict[str, Any]:
    inventory = AirflowProject.scan(project)
    unscheduled = sorted(dag.dag_id for dag in inventory.dags.values() if not dag.schedule)
    catchup_enabled = sorted(dag.dag_id for dag in inventory.dags.values() if dag.catchup is True)
    schedules = Counter(dag.schedule or "NONE" for dag in inventory.dags.values())
    return {
        "mode": "STATIC",
        "schedule_counts": dict(sorted(schedules.items())),
        "unscheduled": unscheduled,
        "catchup_enabled": catchup_enabled,
        "status": "WARN" if catchup_enabled else "PASS",
    }


def backfill_analysis(project: str | Path) -> dict[str, Any]:
    inventory = AirflowProject.scan(project)
    risks = []
    for dag in inventory.dags.values():
        if dag.catchup is True:
            risks.append({"dag_id": dag.dag_id, "risk": "HIGH", "reason": "catchup=True may create historical runs"})
        elif dag.catchup is None:
            risks.append({"dag_id": dag.dag_id, "risk": "REVIEW", "reason": "catchup policy not statically resolved"})
    return {
        "mode": "STATIC",
        "risk_count": len(risks),
        "risks": risks,
        "recommendation": "Use bounded date windows and validate source/target watermarks before backfill execution.",
        "status": "WARN" if risks else "PASS",
    }


def connection_analysis(project: str | Path) -> dict[str, Any]:
    inventory = AirflowProject.scan(project)
    usage: dict[str, list[str]] = defaultdict(list)
    for dag in inventory.dags.values():
        for connection in dag.connections:
            usage[connection].append(dag.dag_id)
    return {
        "mode": "STATIC",
        "connection_count": len(usage),
        "connections": [
            {"connection_id": name, "dag_count": len(dags), "dags": sorted(dags)}
            for name, dags in sorted(usage.items())
        ],
    }


def pipeline_health(project: str | Path) -> dict[str, Any]:
    inventory = AirflowProject.scan(project)
    retry = retry_analysis(project)
    schedule = schedule_analysis(project)
    score = 100
    score -= min(50, len(inventory.parse_errors) * 25)
    score -= min(20, retry["missing_or_zero_count"])
    score -= min(20, len(schedule["catchup_enabled"]) * 5)
    score = max(0, score)
    return {
        "mode": "STATIC",
        "score": score,
        "status": "PASS" if score >= 90 else "WARN" if score >= 70 else "FAIL",
        "components": {
            "dag_parse": {"errors": len(inventory.parse_errors)},
            "retry_policy": {"missing_or_zero": retry["missing_or_zero_count"]},
            "catchup_policy": {"enabled": len(schedule["catchup_enabled"])},
        },
        "live_runtime": "SKIP - Airflow API/database not configured",
    }


def runtime_readiness(project: str | Path) -> dict[str, Any]:
    inventory = AirflowProject.scan(project)
    return {
        "status": "PASS" if inventory.dags and not inventory.parse_errors else "FAIL",
        "static_inventory_ready": bool(inventory.dags),
        "parse_error_count": len(inventory.parse_errors),
        "live_api": "SKIP - runtime endpoint not configured",
        "logs": "SKIP - runtime log source not configured",
        "mode": "STATIC",
    }


def root_cause_from_error(error: str, *, dag_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    lowered = error.casefold()
    rules = [
        (("permission", "not authorized", "insufficient privileges"), "WAREHOUSE_PERMISSION", 0.95,
         "Verify role/grants for the target object and execution identity."),
        (("connection refused", "could not connect", "connection reset"), "CONNECTION_FAILURE", 0.92,
         "Verify the Airflow connection, network route, DNS, and service availability."),
        (("timeout", "timed out", "deadline"), "TIMEOUT", 0.85,
         "Inspect source volume, warehouse sizing, task timeout, and retry policy."),
        (("dbt", "compilation error"), "DBT_FAILURE", 0.88,
         "Inspect dbt run_results/compiled SQL and run the affected selector in isolation."),
        (("snowflake", "sql compilation"), "SNOWFLAKE_SQL_FAILURE", 0.86,
         "Inspect Snowflake query error and compiled SQL before retrying."),
        (("schema", "column", "invalid identifier"), "SCHEMA_DRIFT", 0.82,
         "Compare source/RAW/dbt schemas and quarantine incompatible records."),
    ]
    for terms, cause, confidence, recommendation in rules:
        if any(term in lowered for term in terms):
            return {
                "cause": cause,
                "confidence": confidence,
                "dag_id": dag_id,
                "task_id": task_id,
                "evidence": [error],
                "recommended_action": recommendation,
                "status": "DIAGNOSED",
            }
    return {
        "cause": "UNKNOWN",
        "confidence": 0.25,
        "dag_id": dag_id,
        "task_id": task_id,
        "evidence": [error],
        "recommended_action": "Collect task logs, connection metadata, dbt results, and warehouse query evidence.",
        "status": "NEEDS_MORE_EVIDENCE",
    }


def failure_lab() -> dict[str, Any]:
    error = "SQL access control error: Insufficient privileges to operate on table RAW.PAYMENT_TRANSACTION"
    return {
        "mode": "LOCAL_SIMULATION",
        "event": {
            "dag_id": "postgres_payment_transaction_ingest",
            "task_id": "load_snowflake",
            "state": "FAILED",
            "error": error,
        },
        "diagnosis": root_cause_from_error(
            error,
            dag_id="postgres_payment_transaction_ingest",
            task_id="load_snowflake",
        ),
    }
