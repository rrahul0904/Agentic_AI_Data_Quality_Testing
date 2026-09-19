#!/usr/bin/env python3
"""Generate an Airflow DAG for the RGA synthetic Snowflake + dbt + semantic pipeline."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "airflow" / "dags" / "rga_synthetic_pipeline.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def render_dag() -> str:
    return '''"""Generated Airflow orchestration for the RGA synthetic reinsurance pipeline."""
from __future__ import annotations

import os
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import ShortCircuitOperator

REPO = os.environ.get("RGA_REPO_ROOT", "/opt/airflow/repo")
DBT_DIR = f"{REPO}/rga-snowflake-data-platform/dbt"
SEMANTIC_DIR = f"{REPO}/rga-snowflake-data-platform/semantic"
SQL_DIR = f"{REPO}/snowflake/rga_testbed"
CDC_DIR = f"{REPO}/artifacts/rga_cdc"


def semantic_deploy_enabled(**context):
    return bool(context["params"].get("deploy_semantic_view", False))


def cdc_apply_enabled(**context):
    return bool(context["params"].get("apply_cdc", False))


with DAG(
    dag_id="rga_synthetic_semantic_pipeline",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    params={"preset": "tiny", "seed": 42, "deploy_semantic_view": False, "apply_cdc": False},
    tags=["rga", "synthetic", "snowflake", "dbt", "semantic-view", "cdc"],
) as dag:
    generate_data = BashOperator(
        task_id="generate_synthetic_data",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/generate_data.py "
            "--preset {{ params.preset }} --seed {{ params.seed }}"
        ),
    )

    generate_contracts = BashOperator(
        task_id="generate_pipeline_contracts",
        bash_command=(
            f"cd {REPO} && "
            "python scripts/rga_testbed/generate_snowflake_ddl.py && "
            "python scripts/rga_testbed/generate_load_sql.py && "
            "python scripts/rga_testbed/generate_change_events.py && "
            "python scripts/rga_testbed/generate_cdc_apply_sql.py && "
            "python scripts/rga_testbed/generate_dbt_project.py && "
            "python scripts/rga_testbed/generate_semantic_view.py && "
            "python scripts/rga_testbed/generate_benchmark_pack.py"
        ),
    )

    bootstrap_snowflake = BashOperator(
        task_id="bootstrap_snowflake",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/execute_snowflake_sql.py "
            f"--sql-file {SQL_DIR}/001_raw_tables.sql --confirm"
        ),
    )

    load_raw = BashOperator(
        task_id="load_raw",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/execute_snowflake_sql.py "
            f"--sql-file {SQL_DIR}/002_load_raw.sql --confirm"
        ),
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"cd {DBT_DIR} && cp profiles.yml.example profiles.yml && "
            f"dbt build --project-dir {DBT_DIR} --profiles-dir {DBT_DIR}"
        ),
    )

    verify_semantic_view = BashOperator(
        task_id="verify_semantic_view",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/execute_snowflake_sql.py "
            f"--sql-file {SEMANTIC_DIR}/verify_semantic_view.sql --confirm"
        ),
    )

    cdc_apply_gate = ShortCircuitOperator(
        task_id="cdc_apply_gate",
        python_callable=cdc_apply_enabled,
    )

    capture_cdc_semantic_baseline = BashOperator(
        task_id="capture_cdc_semantic_baseline",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/validate_cdc_semantic_effects.py "
            f"--events {CDC_DIR}/change_events.jsonl "
            f"--baseline {CDC_DIR}/semantic_baseline.json "
            "--mode capture --confirm"
        ),
    )

    apply_cdc = BashOperator(
        task_id="apply_cdc",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/execute_snowflake_sql.py "
            f"--sql-file {SQL_DIR}/003_apply_cdc.sql --confirm"
        ),
    )

    dbt_rebuild_after_cdc = BashOperator(
        task_id="dbt_rebuild_after_cdc",
        bash_command=(
            f"cd {DBT_DIR} && cp profiles.yml.example profiles.yml && "
            f"dbt build --project-dir {DBT_DIR} --profiles-dir {DBT_DIR}"
        ),
    )

    verify_semantic_after_cdc = BashOperator(
        task_id="verify_semantic_after_cdc",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/execute_snowflake_sql.py "
            f"--sql-file {SEMANTIC_DIR}/verify_semantic_view.sql --confirm"
        ),
    )

    validate_cdc_application = BashOperator(
        task_id="validate_cdc_application",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/validate_cdc_application.py "
            f"--events {CDC_DIR}/change_events.jsonl --confirm"
        ),
    )

    validate_cdc_semantic_effects = BashOperator(
        task_id="validate_cdc_semantic_effects",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/validate_cdc_semantic_effects.py "
            f"--events {CDC_DIR}/change_events.jsonl "
            f"--baseline {CDC_DIR}/semantic_baseline.json "
            "--mode validate --confirm"
        ),
    )

    semantic_deploy_gate = ShortCircuitOperator(
        task_id="semantic_deploy_gate",
        python_callable=semantic_deploy_enabled,
    )

    deploy_semantic_view = BashOperator(
        task_id="deploy_semantic_view",
        bash_command=(
            f"cd {REPO} && python scripts/rga_testbed/execute_snowflake_sql.py "
            f"--sql-file {SEMANTIC_DIR}/deploy_semantic_view.sql --confirm"
        ),
    )

    generate_data >> generate_contracts >> bootstrap_snowflake >> load_raw >> dbt_build >> verify_semantic_view
    verify_semantic_view >> semantic_deploy_gate >> deploy_semantic_view
    verify_semantic_view >> cdc_apply_gate >> capture_cdc_semantic_baseline >> apply_cdc
    apply_cdc >> dbt_rebuild_after_cdc >> verify_semantic_after_cdc >> validate_cdc_application >> validate_cdc_semantic_effects
'''


def generate(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dag(), encoding="utf-8")
    return output


def main() -> int:
    path = generate(parse_args().output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
