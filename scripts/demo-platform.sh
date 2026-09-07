#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/dbt-airflow-testing-platform/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(command -v python3)"; fi
export PYTHONPATH="$ROOT/src"

echo "DATA ENGINEERING OS — LOCAL SIMULATION"
echo "== doctor =="
"$PYTHON" -m agentic_data_platform.cli doctor "$ROOT" || true
echo "== hospitality inventory =="
"$PYTHON" -m agentic_data_platform.cli platform inventory --project "$ROOT/hospitality-snowflake-data-platform"
echo "== Airflow health =="
"$PYTHON" -m agentic_data_platform.cli airflow health --project "$ROOT/hospitality-snowflake-data-platform"
echo "== dbt lineage =="
"$PYTHON" -m agentic_data_platform.cli dbt lineage fact_reservation --project "$ROOT/hospitality-snowflake-data-platform"
echo "== cross-system impact =="
"$PYTHON" -m agentic_data_platform.cli platform impact stg_oracle_reservation --project "$ROOT/hospitality-snowflake-data-platform"
echo "== reconciliation (intentional failure) =="
"$PYTHON" -m agentic_data_platform.cli reconcile row-count --source-value 10000 --target-value 9998
echo "== local quality gate =="
(cd "$ROOT/local-data-harness" && npm run quality)
echo "== ShiftForge structured scan =="
"$PYTHON" - <<'PY'
from agentic_data_platform.migration.shiftforge_adapter import ShiftForgeAdapter
from pathlib import Path
root = Path.cwd()
adapter = ShiftForgeAdapter(root / "shiftforge")
print(adapter.inventory(root / "shiftforge" / "examples" / "revinate"))
PY
echo "== final health =="
"$PYTHON" -m agentic_data_platform.cli platform health --project "$ROOT/hospitality-snowflake-data-platform"
echo "Snowflake live integration: SKIP - credentials unavailable unless configured."
echo "Docker runtime: SKIP if Docker daemon is unavailable."
