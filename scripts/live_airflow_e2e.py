#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time

from agentic_data_platform.airflow_compat import AirflowAdapter


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"BLOCKED_EXTERNAL: required environment variable is missing: {name}")
    return value


def state_of(payload):
    return str(payload.get("state") or payload.get("dag_run", {}).get("state") or "").lower()


def run_id_of(payload):
    return payload.get("dag_run_id") or payload.get("run_id") or payload.get("dag_run", {}).get("dag_run_id")


def wait(adapter: AirflowAdapter, dag_id: str, run_id: str, expected: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = adapter.dag_run(dag_id, run_id)
        state = state_of(last)
        if state in {"success", "failed", "error"}:
            if state != expected:
                raise SystemExit(f"Airflow run {run_id} ended {state}, expected {expected}: {last}")
            return last
        time.sleep(3)
    raise SystemExit(f"Airflow run {run_id} did not reach {expected} within {timeout}s; last={last}")


def trigger_and_wait(adapter: AirflowAdapter, dag_id: str, conf: dict, expected: str, timeout: int) -> dict:
    created = adapter.trigger(dag_id, conf=conf)
    if created.get("status") == "ERROR":
        raise SystemExit(f"Airflow trigger failed: {created}")
    run_id = run_id_of(created)
    if not run_id:
        raise SystemExit(f"Airflow trigger response did not contain a run id: {created}")
    final = wait(adapter, dag_id, str(run_id), expected, timeout)
    return {"run_id": run_id, "created": created, "final": final}


def main() -> None:
    if os.getenv("ADE_AIRFLOW_LIVE_MUTATION_APPROVED", "").lower() != "true":
        raise SystemExit("BLOCKED_EXTERNAL: set ADE_AIRFLOW_LIVE_MUTATION_APPROVED=true to authorize the dedicated probe DAG runs")
    adapter = AirflowAdapter(
        required("ADE_AIRFLOW_BASE_URL"),
        version=os.getenv("ADE_AIRFLOW_VERSION"),
        token=os.getenv("ADE_AIRFLOW_TOKEN"),
        username=os.getenv("ADE_AIRFLOW_USERNAME"),
        password=os.getenv("ADE_AIRFLOW_PASSWORD"),
        allow_mutation=True,
    )
    dag_id = os.getenv("ADE_AIRFLOW_DEMO_DAG_ID", "hospitality_agentic_failure_probe")
    timeout = int(os.getenv("ADE_AIRFLOW_LIVE_TIMEOUT_SECONDS", "180"))
    health = adapter.health()
    if health.get("status") == "ERROR":
        raise SystemExit(f"Airflow health failed: {health}")
    dag = adapter.dag(dag_id)
    if dag.get("status") == "ERROR":
        raise SystemExit(f"dedicated probe DAG not available: {dag}")
    failed = trigger_and_wait(adapter, dag_id, {"inject_failure": True}, "failed", timeout)
    recovered = trigger_and_wait(adapter, dag_id, {"inject_failure": False}, "success", timeout)
    print(json.dumps({
        "status": "PASS",
        "mode": "LIVE_AIRFLOW",
        "dag_id": dag_id,
        "health": health,
        "failure_run_id": failed["run_id"],
        "recovery_run_id": recovered["run_id"],
        "failure_recovery": "PASS",
    }, indent=2, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
