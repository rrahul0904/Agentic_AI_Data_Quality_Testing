"""Expose 40 independently schedulable ingestion DAGs from one governed pattern."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup
from common import create_batch_id, discover_or_extract, load_to_snowflake, record_quality, validate_artifacts
from job_catalog import INGESTION_JOBS

from airflow import DAG

DEFAULT_ARGS = {"owner": "hospitality-data-platform", "retries": 2, "retry_delay": timedelta(minutes=5)}


def build_ingestion_dag(spec):
    job = {"dag_id": spec.dag_id, "source": spec.source, "entities": list(spec.entities), "load_strategy": spec.load_strategy}
    with DAG(
        dag_id=spec.dag_id,
        description=f"{spec.source} ingestion for {', '.join(spec.entities)}",
        start_date=datetime(2025, 1, 1, tzinfo=UTC),
        schedule="15 2 * * *",
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["hospitality", "ingestion", spec.source, spec.load_strategy],
        params={"full_refresh": False},
    ) as dag:
        start = EmptyOperator(task_id="start")
        batch = PythonOperator(task_id="create_batch_id", python_callable=create_batch_id, op_kwargs={"source": spec.source, "dag_id": spec.dag_id})
        with TaskGroup("extract") as extract:
            extract_task = PythonOperator(task_id="discover_or_extract", python_callable=discover_or_extract, op_kwargs={"job": job})
        with TaskGroup("validate") as validate:
            validate_task = PythonOperator(task_id="validate_artifacts", python_callable=validate_artifacts)
        with TaskGroup("load") as load:
            load_task = PythonOperator(task_id="load_to_snowflake", python_callable=load_to_snowflake, op_kwargs={"job": job})
        with TaskGroup("quality") as quality:
            quality_task = PythonOperator(task_id="record_quality", python_callable=record_quality)
        finish = EmptyOperator(task_id="finish")
        start >> batch >> extract >> validate >> load >> quality >> finish
        # Bind variables for Airflow graph readability and static analyzers.
        _ = (extract_task, validate_task, load_task, quality_task)
    return dag


for ingestion_spec in INGESTION_JOBS:
    globals()[ingestion_spec.dag_id] = build_ingestion_dag(ingestion_spec)
