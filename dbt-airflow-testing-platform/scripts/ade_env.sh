#!/usr/bin/env bash
# Shared environment for every ADE Test Control Tower process (Airflow
# webserver/scheduler/triggerer, and the demo DAG's tasks). Source this,
# don't execute it: `source scripts/ade_env.sh`.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export AIRFLOW_HOME="$ROOT/airflow_home"
export AIRFLOW__CORE__LOAD_EXAMPLES=false
export AIRFLOW__API__AUTH_BACKENDS="airflow.api.auth.backend.basic_auth"

export ADE_DBT_PROJECT_DIR="$ROOT/dbt_demo_project"
export ADE_DBT_PROFILES_DIR="$ROOT/dbt_demo_project/profiles"
export ADE_DBT_BIN="$ROOT/.venv/bin/dbt"
export ADE_WAREHOUSE_PATH="$ROOT/dbt_demo_project/warehouse/demo.duckdb"

# See scripts/sitecustomize_airflow_macos.py: only needed on macOS setups
# where StandardTaskRunner's os.fork() deadlocks or SIGSEGVs. Harmless
# elsewhere (Linux CI/prod) since the sitecustomize hook is a no-op unless
# this var is set AND it's actually running as an Airflow process.
export ADE_FORCE_EXEC_TASK_RUNNER=1
