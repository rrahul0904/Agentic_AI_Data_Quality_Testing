"""Data Quality Pipeline DAG.

extract_source -> load_to_warehouse (dbt seed) -> run_dbt_models (dbt run)
  -> run_dbt_tests (dbt test) -> [row_count_check, null_rate_check] -> publish_dq_report

This is the "Airflow Data Quality Pipeline" leg that the ADE Test Control
Tower backend triggers via the Airflow REST API for every Test Run. It
deliberately re-runs the same dbt project used by the dbt-only leg, because
in most real stacks dbt tests ARE how the DQ pipeline enforces data quality;
the two extra PythonOperator checks below show how to bolt on checks that
live outside dbt (row-count / null-rate thresholds read straight from the
warehouse).

Configure via environment variables so this DAG works against whatever
checkout of the demo project (or a real one) the operator points it at:
  ADE_DBT_PROJECT_DIR, ADE_DBT_PROFILES_DIR, ADE_DBT_BIN, ADE_WAREHOUSE_PATH
"""

from __future__ import annotations

import os
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

PROJECT_DIR = os.environ.get("ADE_DBT_PROJECT_DIR", "/CHANGE/ME/dbt_demo_project")
PROFILES_DIR = os.environ.get("ADE_DBT_PROFILES_DIR", os.path.join(PROJECT_DIR, "profiles"))
DBT_BIN = os.environ.get("ADE_DBT_BIN", "dbt")
WAREHOUSE_PATH = os.environ.get("ADE_WAREHOUSE_PATH", os.path.join(PROJECT_DIR, "warehouse", "demo.duckdb"))
NULL_RATE_THRESHOLD = float(os.environ.get("ADE_NULL_RATE_THRESHOLD", "0.10"))

DBT_COMMON = f'--project-dir "{PROJECT_DIR}" --profiles-dir "{PROFILES_DIR}" --target dev --no-use-colors'

default_args = {"owner": "ade", "retries": 0}


def extract_source(**_):
    seed_path = os.path.join(PROJECT_DIR, "seeds", "raw_orders.csv")
    if not os.path.exists(seed_path):
        raise FileNotFoundError(f"expected source extract at {seed_path}")
    print(f"source extract available at {seed_path}")


def row_count_check(**_):
    import duckdb

    con = duckdb.connect(WAREHOUSE_PATH, read_only=True)
    count = con.execute("select count(*) from fct_orders").fetchone()[0]
    print(f"fct_orders row_count={count}")
    if count <= 0:
        raise ValueError("fct_orders has zero rows")
    return count


def null_rate_check(**_):
    import duckdb

    con = duckdb.connect(WAREHOUSE_PATH, read_only=True)
    total, nulls = con.execute(
        "select count(*), sum(case when customer_id is null then 1 else 0 end) from stg_orders"
    ).fetchone()
    rate = (nulls or 0) / total if total else 0.0
    print(f"stg_orders.customer_id null_rate={rate:.2%} (threshold {NULL_RATE_THRESHOLD:.0%})")
    if rate > NULL_RATE_THRESHOLD:
        raise ValueError(f"null rate {rate:.2%} exceeds threshold {NULL_RATE_THRESHOLD:.0%}")
    return rate


def publish_dq_report(**context):
    ti = context["ti"]
    row_count_value = ti.xcom_pull(task_ids="row_count_check")
    null_rate_value = ti.xcom_pull(task_ids="null_rate_check")
    print(f"DQ REPORT: fct_orders.row_count={row_count_value} stg_orders.null_rate={null_rate_value}")


with DAG(
    dag_id="data_quality_pipeline",
    description="Extract, load, transform (dbt), test (dbt), and check data quality end to end.",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["ade", "data-quality"],
) as dag:
    extract = PythonOperator(task_id="extract_source", python_callable=extract_source)

    load = BashOperator(
        task_id="load_to_warehouse", bash_command=f'"{DBT_BIN}" seed {DBT_COMMON}', cwd=PROJECT_DIR
    )

    run_models = BashOperator(
        task_id="run_dbt_models", bash_command=f'"{DBT_BIN}" run {DBT_COMMON}', cwd=PROJECT_DIR
    )

    run_tests = BashOperator(
        task_id="run_dbt_tests", bash_command=f'"{DBT_BIN}" test {DBT_COMMON}', cwd=PROJECT_DIR
    )

    row_count = PythonOperator(task_id="row_count_check", python_callable=row_count_check)
    null_rate = PythonOperator(task_id="null_rate_check", python_callable=null_rate_check)

    report = PythonOperator(task_id="publish_dq_report", python_callable=publish_dq_report)

    extract >> load >> run_models >> run_tests >> [row_count, null_rate] >> report
