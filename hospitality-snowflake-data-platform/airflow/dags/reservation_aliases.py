"""Stable reservation-domain DAG names backed by the metadata-driven factory."""

from __future__ import annotations

from datetime import UTC, datetime

from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.utils.task_group import TaskGroup
from common import create_batch_id, discover_or_extract, load_to_snowflake, record_quality, validate_artifacts
from job_catalog import INGESTION_JOBS

from airflow import DAG

_ALIASES = {
    "oracle_reservation_ingest": "07_oracle_reservation_header_ingest",
    "oracle_reservation_room_ingest": "08_oracle_reservation_room_ingest",
    "oracle_guest_ingest": "05_oracle_guest_profile_ingest",
    "oracle_room_ingest": "02_oracle_room_inventory_ingest",
    "postgres_booking_attempt_ingest": "26_postgres_booking_attempt_ingest",
    "postgres_booking_confirmation_ingest": "27_postgres_booking_confirmation_ingest",
    "postgres_payment_transaction_ingest": "28_postgres_payment_transaction_ingest",
    "postgres_refund_transaction_ingest": "29_postgres_refund_transaction_ingest",
}


def _build_alias(spec, alias):
    job = {"dag_id": alias, "source": spec.source, "entities": list(spec.entities), "load_strategy": spec.load_strategy}
    with DAG(alias, start_date=datetime(2025, 1, 1, tzinfo=UTC), schedule="15 2 * * *", catchup=False,
             max_active_runs=1, tags=["hospitality", "reservation", spec.source],
             default_args={"owner": "hospitality-data-platform", "retries": 2}) as dag:
        start = EmptyOperator(task_id="start")
        batch = PythonOperator(task_id="create_batch_id", python_callable=create_batch_id, op_kwargs={"source": spec.source, "dag_id": alias})
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
        _ = (extract_task, validate_task, load_task, quality_task)
    return dag


for alias, source_dag_id in _ALIASES.items():
    source_spec = next(spec for spec in INGESTION_JOBS if spec.dag_id == source_dag_id)
    globals()[alias] = _build_alias(source_spec, alias)


with DAG(
    "hospitality_reservation_master",
    start_date=datetime(2025, 1, 1, tzinfo=UTC),
    schedule="0 1 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["hospitality", "reservation", "master"],
) as hospitality_reservation_master:
    start = EmptyOperator(task_id="start")
    triggers = [
        TriggerDagRunOperator(task_id=f"run_{dag_id}", trigger_dag_id=dag_id, wait_for_completion=True)
        for dag_id in _ALIASES
    ]
    finish = EmptyOperator(task_id="finish")
    start >> triggers >> finish
