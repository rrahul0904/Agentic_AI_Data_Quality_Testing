#!/usr/bin/env bash
# One-time setup of the Airflow venv used for the "Airflow data-quality
# pipeline" leg. Kept in its own venv (.airflow_venv) separate from the
# backend/dbt venv (.venv) because Airflow and dbt-core pin conflicting
# transitive dependencies (SQLAlchemy, Jinja2, etc.).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

AIRFLOW_VERSION="2.10.5"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> Creating $ROOT/.airflow_venv"
"$PYTHON_BIN" -m venv .airflow_venv
source .airflow_venv/bin/activate
pip install -q --upgrade pip

PYTHON_MM="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_MM}.txt"

echo "==> Installing apache-airflow==${AIRFLOW_VERSION} (python ${PYTHON_MM}, constraints from ${CONSTRAINT_URL})"
pip install -q "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}"
pip install -q duckdb  # used directly (no dbt) by the row_count/null_rate DQ check tasks

echo "==> Applying macOS fork-safety patch to .airflow_venv/bin/airflow"
python3 "$ROOT/scripts/patch_airflow_entrypoint.py" "$ROOT/.airflow_venv"

echo "==> Done. Next: scripts/init_airflow_db.sh"
