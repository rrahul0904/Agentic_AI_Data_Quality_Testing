"""Dedicated, safe live-E2E probe DAG for failure → recovery verification."""

from __future__ import annotations

from datetime import UTC, datetime

from airflow import DAG

try:
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:
    from airflow.operators.python import PythonOperator


def probe(**context):
    conf = dict(getattr(context.get("dag_run"), "conf", None) or {})
    if conf.get("inject_failure"):
        raise RuntimeError("AGENTIC_E2E_INTENTIONAL_FAILURE")
    return {"status": "PASS", "probe": "agentic_failure_recovery"}


with DAG(
    "hospitality_agentic_failure_probe",
    start_date=datetime(2025, 1, 1, tzinfo=UTC),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["hospitality", "agentic", "live-e2e"],
) as hospitality_agentic_failure_probe:
    PythonOperator(task_id="probe", python_callable=probe)
