#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export ADE_DEMO_MODE=true
export ADE_DEMO_PROJECT="$ROOT/hospitality-snowflake-data-platform"
export ADE_DATABASE_PATH="$ROOT/.ade/demo-airflow.db"
echo "=== AIRFLOW CONTROL PLANE · LOCAL_SIMULATION ==="
python - <<'PY'
from fastapi.testclient import TestClient
from agentic_data_platform.api.app import create_app

client = TestClient(create_app())
checks = [
    ("inventory", "GET", "/api/v1/airflow/inventory", None),
    ("dags", "GET", "/api/v1/airflow/dags", None),
    ("assets", "GET", "/api/v1/airflow/assets", None),
    ("operations", "GET", "/api/v1/airflow/operations", None),
    ("capacity", "GET", "/api/v1/airflow/capacity", None),
    ("upgrade", "GET", "/api/v1/airflow/upgrade", None),
    ("security", "GET", "/api/v1/airflow/security", None),
    ("bundles", "GET", "/api/v1/airflow/bundles", None),
    ("failure_lab", "GET", "/api/v1/airflow/failure-lab", None),
    ("backfill_plan", "POST", "/api/v1/airflow/backfill/plan", {"args":{"dag_id":"hospitality_master","start_date":"2026-09-01","end_date":"2026-09-03"}}),
]
for label, method, path, body in checks:
    response = client.request(method, path, json=body)
    if response.status_code >= 400:
        raise SystemExit(f"{label}: HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    status = payload.get("status", payload.get("mode", "PASS")) if isinstance(payload, dict) else "PASS"
    print(f"{label:18} {status}")
print("AIRFLOW DEMO: PASS")
PY
