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


FAILURE_FIXTURES: dict[str, dict[str, Any]] = {
    "bad_connection": {
        "error": "Connection refused by source database host while opening conn_id=oracle_pms",
        "expected": "CONNECTION_FAILURE",
        "asset": "oracle_pms.reservation",
    },
    "missing_connection": {
        "error": "AirflowNotFoundException: The conn_id 'postgres_crm' isn't defined",
        "expected": "MISSING_CONNECTION",
        "asset": "postgres_crm",
    },
    "bad_credentials": {
        "error": "Authentication failed: invalid username/password for Airflow connection",
        "expected": "CREDENTIAL_FAILURE",
        "asset": "warehouse_connection",
    },
    "permission_denied": {
        "error": "Permission denied while reading source table HOTEL.RESERVATION",
        "expected": "WAREHOUSE_PERMISSION",
        "asset": "HOTEL.RESERVATION",
    },
    "warehouse_unavailable": {
        "error": "Warehouse unavailable: service is temporarily unavailable",
        "expected": "WAREHOUSE_UNAVAILABLE",
        "asset": "warehouse",
    },
    "dbt_compile_failure": {
        "error": "dbt Compilation Error in model fact_reservation: invalid ref",
        "expected": "DBT_COMPILE_FAILURE",
        "asset": "fact_reservation",
    },
    "dbt_test_failure": {
        "error": "dbt test failure: not_null_fact_reservation_reservation_id returned 27 failures",
        "expected": "DBT_TEST_FAILURE",
        "asset": "fact_reservation",
    },
    "schema_drift": {
        "error": "Schema drift detected: column guest_status changed type from VARCHAR to NUMBER",
        "expected": "SCHEMA_DRIFT",
        "asset": "guest_status",
    },
    "missing_source_table": {
        "error": "Source table not found: ORACLE_PMS.HOTEL_STAY",
        "expected": "MISSING_SOURCE_TABLE",
        "asset": "ORACLE_PMS.HOTEL_STAY",
    },
    "late_source_data": {
        "error": "Late source data: freshness threshold exceeded by 190 minutes",
        "expected": "LATE_SOURCE_DATA",
        "asset": "reservation_feed",
    },
    "duplicate_data": {
        "error": "Duplicate data detected for reservation_id; uniqueness check failed",
        "expected": "DUPLICATE_DATA",
        "asset": "reservation_id",
    },
    "watermark_regression": {
        "error": "Watermark regression: new high_watermark 2026-09-01 precedes stored watermark 2026-09-02",
        "expected": "WATERMARK_REGRESSION",
        "asset": "ingestion_watermark",
    },
    "timeout": {
        "error": "Task timed out after execution_timeout=3600 seconds",
        "expected": "TIMEOUT",
        "asset": "airflow_task",
    },
    "retry_storm": {
        "error": "Retry storm detected: task has retried 18 times across mapped task instances",
        "expected": "RETRY_STORM",
        "asset": "airflow_task",
    },
    "stuck_sensor": {
        "error": "Sensor stuck in sensing state for 8 hours using poke mode",
        "expected": "STUCK_SENSOR",
        "asset": "sensor_task",
    },
    "pool_starvation": {
        "error": "Pool starvation: no open slots in pool snowflake_heavy",
        "expected": "POOL_STARVATION",
        "asset": "snowflake_heavy",
    },
    "queue_starvation": {
        "error": "Queue starvation: task queued for 95 minutes with no matching worker",
        "expected": "QUEUE_STARVATION",
        "asset": "etl_queue",
    },
    "dynamic_map_explosion": {
        "error": "Dynamic map explosion: mapped task cardinality 250000 exceeds max_map_length",
        "expected": "DYNAMIC_MAP_EXPLOSION",
        "asset": "mapped_task",
    },
    "xcom_oversize": {
        "error": "XCom payload oversize: serialized value exceeds backend limit",
        "expected": "XCOM_OVERSIZE",
        "asset": "xcom",
    },
    "dag_import_failure": {
        "error": "DAG import failure: ModuleNotFoundError while parsing dags/reservation.py",
        "expected": "DAG_IMPORT_FAILURE",
        "asset": "reservation.py",
    },
    "deprecated_airflow_api": {
        "error": "Deprecated Airflow API import: airflow.models.baseoperator is not supported in Airflow 3",
        "expected": "DEPRECATED_AIRFLOW_API",
        "asset": "dag_source",
    },
    "asset_event_missing": {
        "error": "Asset event missing: consumer DAG waiting for asset://raw/reservation",
        "expected": "ASSET_EVENT_MISSING",
        "asset": "asset://raw/reservation",
    },
    "triggerer_unavailable": {
        "error": "Triggerer unavailable: deferred task cannot resume because no triggerer heartbeat exists",
        "expected": "TRIGGERER_UNAVAILABLE",
        "asset": "triggerer",
    },
    "bundle_version_mismatch": {
        "error": "DAG bundle version mismatch: run requested v17 but current bundle is v19",
        "expected": "BUNDLE_VERSION_MISMATCH",
        "asset": "dag_bundle",
    },
    "snowflake_permission_error": {
        "error": "SQL access control error: Insufficient privileges to operate on table RAW.PAYMENT_TRANSACTION",
        "expected": "WAREHOUSE_PERMISSION",
        "asset": "RAW.PAYMENT_TRANSACTION",
    },
}


def root_cause_from_error(
    error: str,
    *,
    dag_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    lowered = error.casefold()
    rules = [
        (("conn_id", "isn't defined"), "MISSING_CONNECTION", 0.99,
         "Create or restore the referenced Airflow connection through the approved secret-safe connection path."),
        (("authentication failed", "invalid username/password", "invalid credential"), "CREDENTIAL_FAILURE", 0.98,
         "Rotate or repair credentials in the configured secret backend; do not hard-code credentials in DAG code."),
        (("pool starvation", "no open slots in pool"), "POOL_STARVATION", 0.98,
         "Inspect pool occupancy and either free or deliberately resize the constrained pool."),
        (("queue starvation", "no matching worker"), "QUEUE_STARVATION", 0.98,
         "Verify executor queue routing and matching worker capacity before retrying."),
        (("dynamic map explosion", "max_map_length"), "DYNAMIC_MAP_EXPLOSION", 0.99,
         "Bound mapped input cardinality, batch work, and validate max_map_length before execution."),
        (("xcom payload oversize", "serialized value exceeds"), "XCOM_OVERSIZE", 0.98,
         "Move large payloads to object/warehouse storage and pass only a reference through XCom."),
        (("dag import failure", "modulenotfounderror"), "DAG_IMPORT_FAILURE", 0.98,
         "Repair the DAG dependency/import and verify parse health before scheduling runs."),
        (("deprecated airflow api", "not supported in airflow 3"), "DEPRECATED_AIRFLOW_API", 0.97,
         "Migrate to supported public Airflow 3 / airflow.sdk imports and rerun compatibility analysis."),
        (("asset event missing", "waiting for asset://"), "ASSET_EVENT_MISSING", 0.96,
         "Verify producer task completion, emitted Asset event, partition key, and consumer schedule conditions."),
        (("triggerer unavailable", "no triggerer heartbeat"), "TRIGGERER_UNAVAILABLE", 0.99,
         "Restore triggerer health before resuming deferrable operators."),
        (("bundle version mismatch", "current bundle"), "BUNDLE_VERSION_MISMATCH", 0.99,
         "Reconcile the requested and current DAG bundle versions before rerunning historical work."),
        (("watermark regression", "high_watermark"), "WATERMARK_REGRESSION", 0.99,
         "Block the incremental load, inspect source chronology, and repair the watermark under explicit approval."),
        (("retry storm", "retried"), "RETRY_STORM", 0.97,
         "Classify the error as retryable/non-retryable and cap retries/backoff before resuming."),
        (("sensor stuck", "poke mode"), "STUCK_SENSOR", 0.96,
         "Inspect the awaited condition and migrate to reschedule/deferrable behavior where supported."),
        (("late source data", "freshness threshold"), "LATE_SOURCE_DATA", 0.97,
         "Validate source arrival SLA/deadline and hold downstream publication until freshness is restored."),
        (("duplicate data", "uniqueness check failed"), "DUPLICATE_DATA", 0.97,
         "Quarantine duplicate keys and reconcile source/target uniqueness before downstream publication."),
        (("source table not found", "missing source table"), "MISSING_SOURCE_TABLE", 0.98,
         "Confirm source schema/catalog drift and repair the source mapping before retrying."),
        (("dbt test failure", "returned 27 failures"), "DBT_TEST_FAILURE", 0.98,
         "Inspect dbt run_results and failing rows; do not publish affected downstream assets."),
        (("dbt compilation error", "compilation error in model"), "DBT_COMPILE_FAILURE", 0.98,
         "Fix dbt parse/compile errors and rerun deterministic dbt completion validators."),
        (("warehouse unavailable", "service is temporarily unavailable"), "WAREHOUSE_UNAVAILABLE", 0.96,
         "Confirm warehouse/service health and retry only after availability is restored."),
        (("permission denied", "insufficient privileges", "not authorized", "access control error"), "WAREHOUSE_PERMISSION", 0.95,
         "Verify role/grants for the target object and execution identity."),
        (("connection refused", "could not connect", "connection reset"), "CONNECTION_FAILURE", 0.92,
         "Verify the Airflow connection, network route, DNS, and service availability."),
        (("timed out", "timeout", "deadline"), "TIMEOUT", 0.90,
         "Inspect source volume, warehouse sizing, execution timeout, deadline, and retry policy."),
        (("schema drift", "invalid identifier", "column changed type"), "SCHEMA_DRIFT", 0.92,
         "Compare source/RAW/dbt schemas and quarantine incompatible records."),
        (("snowflake", "sql compilation"), "SNOWFLAKE_SQL_FAILURE", 0.86,
         "Inspect Snowflake query error and compiled SQL before retrying."),
        (("dbt", "compilation"), "DBT_FAILURE", 0.82,
         "Inspect dbt run_results/compiled SQL and run the affected selector in isolation."),
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
        "recommended_action": "Collect task logs, connection metadata, dbt results, quality evidence, and warehouse query evidence.",
        "status": "NEEDS_MORE_EVIDENCE",
    }


def failure_lab(case: str = "snowflake_permission_error") -> dict[str, Any]:
    if case not in FAILURE_FIXTURES:
        raise KeyError(f"unknown Airflow failure fixture: {case}")
    fixture = FAILURE_FIXTURES[case]
    dag_id = f"failure_lab_{case}"
    task_id = "diagnose"
    diagnosis = root_cause_from_error(
        str(fixture["error"]),
        dag_id=dag_id,
        task_id=task_id,
    )
    matrix = []
    for name, candidate in FAILURE_FIXTURES.items():
        result = root_cause_from_error(str(candidate["error"]), dag_id=f"failure_lab_{name}", task_id="diagnose")
        matrix.append({
            "name": name,
            "symptom": candidate["error"],
            "detected_evidence": result["evidence"],
            "root_cause": result["cause"],
            "expected_root_cause": candidate["expected"],
            "affected_assets": [candidate["asset"]],
            "recommended_response": result["recommended_action"],
            "status": "PASS" if result["cause"] == candidate["expected"] else "FAIL",
        })
    return {
        "mode": "LOCAL_SIMULATION",
        "fixture_count": len(matrix),
        "all_fixture_diagnoses_match": all(item["status"] == "PASS" for item in matrix),
        "fixtures": matrix,
        "event": {
            "dag_id": dag_id,
            "task_id": task_id,
            "state": "FAILED",
            "error": fixture["error"],
        },
        "diagnosis": diagnosis,
    }

