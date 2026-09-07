#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
PY_MINOR="$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

echo "Using Python ${PY_MINOR}"

$PYTHON -m venv .venv-data
.venv-data/bin/python -m pip install --upgrade pip
.venv-data/bin/pip install \
  'snowflake-connector-python==4.7.3' \
  'dbt-core==1.12.3' \
  'dbt-snowflake==1.12.0'

$PYTHON -m venv .venv-airflow
.venv-airflow/bin/python -m pip install --upgrade pip
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-${PY_MINOR}.txt"
.venv-airflow/bin/pip install \
  'apache-airflow==3.3.1' \
  'apache-airflow-providers-snowflake==6.16.1' \
  --constraint "$CONSTRAINT_URL"

cat <<MSG

Installed optional data stack.
Run these in your shell before LDH integration tests:
  export LDH_PYTHON_BIN="$ROOT/.venv-data/bin/python"
  export LDH_DBT_BIN="$ROOT/.venv-data/bin/dbt"
  export LDH_AIRFLOW_BIN="$ROOT/.venv-airflow/bin/airflow"

Then:
  node src/cli/index.mjs quality --cwd examples/demo --level static
  node src/cli/index.mjs quality --cwd examples/demo --level integration
MSG
