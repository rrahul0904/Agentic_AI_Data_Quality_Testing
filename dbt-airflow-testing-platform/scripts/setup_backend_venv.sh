#!/usr/bin/env bash
# One-time setup of the backend venv: FastAPI backend + dbt-core + dbt-duckdb
# (the "dbt testing" leg runs from this same venv, via an absolute path to
# its `dbt` executable, so Airflow's BashOperator tasks can call it too).
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt

mkdir -p dbt_demo_project/warehouse

echo "==> Done. Next: scripts/run_backend.sh"
