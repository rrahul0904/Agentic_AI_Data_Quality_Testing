#!/usr/bin/env python3
"""Strict Airflow capability gate: ledger status + required semantic surface."""

from __future__ import annotations

import json
from pathlib import Path

from check_parity_gate import check_ledger

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "specs" / "AIRFLOW_CAPABILITY_LEDGER.json"
REQUIRED = {
    "airflow_inventory", "airflow_graph", "airflow_dag_lineage", "airflow_task_lineage",
    "airflow_asset_inventory", "airflow_asset_dependencies", "airflow_asset_events",
    "airflow_event_schedule_analysis", "airflow_asset_watchers", "airflow_event_stalls",
    "airflow_dynamic_mapping_analysis", "airflow_mapping_risk", "airflow_mapping_cardinality",
    "airflow_deferrable_analysis", "airflow_triggerer_health", "airflow_sensor_efficiency",
    "airflow_bundle_inventory", "airflow_bundle_versions", "airflow_bundle_security", "airflow_bundle_drift",
    "airflow_sdk_compatibility", "airflow_upgrade_analysis", "airflow_import_errors", "airflow_parse_health",
    "airflow_duplicate_dags", "airflow_failed_dags", "airflow_failed_tasks", "airflow_retry_analysis",
    "airflow_retry_policy_analysis", "airflow_retry_storms", "airflow_duration_analysis",
    "airflow_queue_analysis", "airflow_pool_analysis", "airflow_scheduler_health",
    "airflow_dag_processor_health", "airflow_worker_health", "airflow_deadline_analysis",
    "airflow_pipeline_health", "airflow_root_cause", "airflow_task_root_cause",
    "airflow_pipeline_root_cause", "airflow_backfill_plan", "airflow_backfill_risk",
    "airflow_backfill_dry_run", "airflow_deadline_health", "airflow_connections_used",
    "airflow_connection_impact", "airflow_variables_used", "airflow_secret_risk",
    "airflow_xcom_analysis", "airflow_xcom_risk", "airflow_pool_health", "airflow_queue_health",
    "airflow_concurrency_analysis", "airflow_capacity_plan", "airflow_executor_analysis",
    "airflow_log_summary", "airflow_log_errors", "airflow_log_root_cause",
    "airflow_openlineage_status", "airflow_openlineage_events", "airflow_openlineage_graph",
    "airflow_deployment_readiness", "airflow_doctor", "airflow_quality_scan",
    "airflow_runtime_dags", "airflow_runtime_dag_runs", "airflow_runtime_task_instances",
    "airflow_runtime_logs", "airflow_runtime_assets", "airflow_runtime_import_errors",
    "airflow_trigger", "airflow_pause", "airflow_unpause", "airflow_clear", "airflow_backfill_execute",
}


def main() -> int:
    ok, counts, errors = check_ledger("airflow")
    data = json.loads(LEDGER.read_text())
    present = {item["capability"] for item in data["entries"]}
    missing = sorted(REQUIRED - present)
    if missing:
        errors.append("required capabilities absent from ledger: " + ", ".join(missing))
        ok = False
    print(f"AIRFLOW CAPABILITY GATE: {'PASS' if ok else 'FAIL'} {counts}")
    for error in errors:
        print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
