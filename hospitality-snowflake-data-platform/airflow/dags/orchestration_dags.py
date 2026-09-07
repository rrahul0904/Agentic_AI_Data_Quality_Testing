"""Master ingestion, dbt, quality, and end-to-end orchestration DAGs."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.utils.task_group import TaskGroup
from job_catalog import INGESTION_JOBS

from airflow import DAG

START_DATE = datetime(2025, 1, 1, tzinfo=UTC)

with DAG(
    "hospitality_daily_raw_ingestion_master", start_date=START_DATE, schedule="0 2 * * *", catchup=False,
    max_active_runs=1, tags=["hospitality", "master"],
) as hospitality_daily_raw_ingestion_master:
    begin = EmptyOperator(task_id="start")
    groups = []
    for source in ("oracle", "postgres", "files"):
        with TaskGroup(group_id=f"trigger_{source}_ingestion") as group:
            triggers = [
                TriggerDagRunOperator(
                    task_id=f"trigger_{spec.dag_id}", trigger_dag_id=spec.dag_id,
                    wait_for_completion=True, reset_dag_run=True,
                )
                for spec in INGESTION_JOBS if spec.source == source
            ]
        groups.append(group)
        _ = triggers
    finish = EmptyOperator(task_id="finish")
    begin >> groups >> finish


def dbt_dag(dag_id: str, selector: str):
    with DAG(dag_id, start_date=START_DATE, schedule=None, catchup=False, tags=["hospitality", "dbt"]) as dag:
        BashOperator(
            task_id="dbt_build",
            bash_command=f"cd /opt/airflow/dbt && dbt build --profiles-dir . --select {selector}",
            env={"DBT_PROFILES_DIR": "/opt/airflow/dbt"},
            append_env=True,
        )
    return dag


hospitality_dbt_staging_run = dbt_dag("hospitality_dbt_staging_run", "path:models/staging")
hospitality_dbt_core_run = dbt_dag("hospitality_dbt_core_run", "path:models/intermediate path:models/core")
hospitality_dbt_mart_run = dbt_dag("hospitality_dbt_mart_run", "path:models/marts")

with DAG(
    "hospitality_data_quality_master", start_date=START_DATE, schedule=None, catchup=False,
    tags=["hospitality", "quality"],
) as hospitality_data_quality_master:
    BashOperator(
        task_id="dbt_test", bash_command="cd /opt/airflow/dbt && dbt test --profiles-dir .",
        env={"DBT_PROFILES_DIR": "/opt/airflow/dbt"}, append_env=True,
    )

with DAG(
    "hospitality_end_to_end_pipeline", start_date=START_DATE, schedule="0 1 * * *", catchup=False,
    max_active_runs=1, tags=["hospitality", "end-to-end"],
) as hospitality_end_to_end_pipeline:
    sequence = [
        TriggerDagRunOperator(task_id=f"run_{target}", trigger_dag_id=target, wait_for_completion=True)
        for target in (
            "hospitality_daily_raw_ingestion_master", "hospitality_dbt_staging_run",
            "hospitality_dbt_core_run", "hospitality_dbt_mart_run", "hospitality_data_quality_master",
        )
    ]
    for upstream, downstream in pairwise(sequence):
        upstream >> downstream
