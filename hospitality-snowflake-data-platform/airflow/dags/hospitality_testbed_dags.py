"""Airflow orchestration for the reusable hospitality Snowflake testbed scripts."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.task_group import TaskGroup

from airflow import DAG

PROJECT_ROOT = os.environ.get("ADE_TESTBED_PROJECT_ROOT", "/opt/airflow/project")
PYTHON = os.environ.get("ADE_TESTBED_PYTHON", "python3")
SCRIPTS = f"{PROJECT_ROOT}/scripts/hospitality_testbed"
DEFAULT_ARGS = {"owner": "hospitality-testbed", "retries": 1, "retry_delay": timedelta(minutes=3)}

COMMANDS = {
    "generate_testbed_data": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/generate_data.py --preset ${{ADE_TESTBED_SCALE:-tiny}} --seed ${{ADE_TESTBED_SEED:-42}}",
    "validate_landing_files": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/validate_files.py",
    "upload_testbed_files": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/upload_to_s3.py",
    "snowflake_manual_backfill": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/stage_internal_files.py && {PYTHON} {SCRIPTS}/run_copy_loads.py --mode local",
    "snowpipe_monitor": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/monitor_snowpipe.py",
    "raw_data_quality": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/validate_pipeline.py && {PYTHON} {SCRIPTS}/run_snowflake_dq.py --layer raw",
    "stream_monitor": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/monitor_streams.py",
    "cdc_processing": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/consume_streams.py --execute",
    "dbt_staging_build": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/run_dbt.py --layer staging",
    "dbt_core_build": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/run_dbt.py --layer core",
    "dbt_marts_build": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/run_dbt.py --layer marts",
    "reconciliation": f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/reconcile_pipeline.py",
    "ade_snowflake_certification": f"cd {PROJECT_ROOT} && PYTHONPATH=src {PYTHON} {SCRIPTS}/certify_with_ade.py --mode ${{ADE_TESTBED_MODE:-live}}",
}


def script_dag(dag_id: str, command: str) -> DAG:
    with DAG(
        dag_id=dag_id,
        description=f"Hospitality Snowflake testbed: {dag_id.replace('_', ' ')}",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        schedule=None,
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["hospitality", "snowflake", "testbed"],
    ) as dag:
        BashOperator(task_id="run_reusable_script", bash_command=command, cwd=PROJECT_ROOT)
    return dag


for _dag_id, _command in COMMANDS.items():
    globals()[_dag_id] = script_dag(_dag_id, _command)


with DAG(
    dag_id="hospitality_end_to_end",
    description="Generate, ingest, transform, reconcile, and certify the hospitality testbed",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={"mode": "local"},
    tags=["hospitality", "snowflake", "testbed", "end-to-end"],
) as hospitality_end_to_end:
    start = EmptyOperator(task_id="start")
    with TaskGroup("landing") as landing:
        generate = BashOperator(task_id="generate", bash_command=COMMANDS["generate_testbed_data"], cwd=PROJECT_ROOT)
        validate = BashOperator(task_id="validate", bash_command=COMMANDS["validate_landing_files"], cwd=PROJECT_ROOT)
        bootstrap = BashOperator(
            task_id="bootstrap_snowflake",
            bash_command=f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/bootstrap_snowflake.py --mode ${{ADE_TESTBED_MODE:-local}}",
            cwd=PROJECT_ROOT,
        )
        upload_or_stage = BashOperator(
            task_id="upload_or_stage",
            bash_command=f"cd {PROJECT_ROOT} && if [ \"${{ADE_TESTBED_MODE:-local}}\" = live ]; then {PYTHON} {SCRIPTS}/upload_to_s3.py; else {PYTHON} {SCRIPTS}/stage_internal_files.py; fi",
            cwd=PROJECT_ROOT,
        )
        load_or_wait = BashOperator(
            task_id="load_or_wait_for_snowpipe",
            bash_command=f"cd {PROJECT_ROOT} && if [ \"${{ADE_TESTBED_MODE:-local}}\" = live ]; then {PYTHON} {SCRIPTS}/run_copy_loads.py --mode live --exclude-snowpipe && {PYTHON} {SCRIPTS}/monitor_snowpipe.py; else {PYTHON} {SCRIPTS}/run_copy_loads.py --mode local; fi",
            cwd=PROJECT_ROOT,
        )
        generate >> validate >> bootstrap >> upload_or_stage >> load_or_wait
    with TaskGroup("raw_and_cdc") as raw_and_cdc:
        raw_dq = BashOperator(task_id="raw_dq", bash_command=COMMANDS["raw_data_quality"], cwd=PROJECT_ROOT)
        stream_check = BashOperator(task_id="stream_check", bash_command=COMMANDS["stream_monitor"], cwd=PROJECT_ROOT)
        cdc = BashOperator(task_id="consume_approved_streams", bash_command=COMMANDS["cdc_processing"], cwd=PROJECT_ROOT)
        raw_dq >> stream_check >> cdc
    with TaskGroup("dbt") as dbt_build:
        staging = BashOperator(task_id="staging", bash_command=COMMANDS["dbt_staging_build"], cwd=PROJECT_ROOT)
        core = BashOperator(task_id="core", bash_command=COMMANDS["dbt_core_build"], cwd=PROJECT_ROOT)
        marts = BashOperator(task_id="marts", bash_command=COMMANDS["dbt_marts_build"], cwd=PROJECT_ROOT)
        staging >> core >> marts
    transformed_dq = BashOperator(
        task_id="transformed_data_quality",
        bash_command=f"cd {PROJECT_ROOT} && {PYTHON} {SCRIPTS}/run_snowflake_dq.py --layer transformed",
        cwd=PROJECT_ROOT,
    )
    reconcile = BashOperator(task_id="reconcile", bash_command=COMMANDS["reconciliation"], cwd=PROJECT_ROOT)
    certify = BashOperator(task_id="certify_with_ade", bash_command=COMMANDS["ade_snowflake_certification"], cwd=PROJECT_ROOT)
    finish = EmptyOperator(task_id="finish")
    start >> landing >> raw_and_cdc >> dbt_build >> transformed_dq >> reconcile >> certify >> finish
