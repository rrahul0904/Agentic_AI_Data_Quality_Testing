#!/usr/bin/env bash
# One-time (per fresh airflow_home): migrate the metadata DB, register the
# demo DAG, and create an admin user for the REST API / UI.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/ade_env.sh
source .airflow_venv/bin/activate

mkdir -p "$AIRFLOW_HOME/dags"
ln -sf "$(pwd)/airflow_dags/data_quality_pipeline_dag.py" "$AIRFLOW_HOME/dags/data_quality_pipeline_dag.py"
mkdir -p dbt_demo_project/warehouse

airflow db migrate

airflow users create \
  --username admin --password admin123 \
  --firstname Admin --lastname User --role Admin --email admin@example.com \
  || echo "(admin user already exists, skipping)"

airflow dags unpause data_quality_pipeline || true

echo "==> Airflow metadata DB ready at $AIRFLOW_HOME"
echo "==> Login: admin / admin123 (change this before using anywhere but localhost)"
