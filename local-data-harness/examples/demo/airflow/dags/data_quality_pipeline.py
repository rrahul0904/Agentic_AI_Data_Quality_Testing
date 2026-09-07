"""Local Data Harness example: orchestrate dbt tests and a Snowflake health gate."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

from airflow.sdk import dag, task
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook


@dag(
    dag_id="ldh_data_quality_pipeline",
    schedule="0 6 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    default_args={"retries": 1},
    tags=["ldh", "dbt", "snowflake", "data-quality"],
)
def data_quality_pipeline():
    @task
    def dbt_test() -> None:
        project_dir = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt")
        subprocess.run(["dbt", "test", "--project-dir", project_dir], check=True)

    @task
    def snowflake_health() -> str:
        hook = SnowflakeHook(snowflake_conn_id="snowflake_default")
        row = hook.get_first("select current_version()")
        return str(row[0])

    dbt_test() >> snowflake_health()


data_quality_pipeline()
