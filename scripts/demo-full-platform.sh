#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export ADE_DEMO_MODE=true
export ADE_DEMO_PROJECT="$ROOT/hospitality-snowflake-data-platform"
export ADE_QUALITY_DATABASE="$ROOT/.ade/demo-quality.db"
export ADE_DATABASE_PATH="$ROOT/.ade/demo-control.db"
mkdir -p "$ROOT/.ade"
python scripts/parse_dbt.py >/dev/null
python scripts/init_demo_evidence.py >/dev/null

echo "=== AGENTIC DATA ENGINEERING OS · MASTER DEMO · LOCAL_SIMULATION ==="
python - <<'PY'
from fastapi.testclient import TestClient
from agentic_data_platform.api.app import create_app

client = TestClient(create_app())
checks = [
    ("doctor", "GET", "/api/v1/platform/health", None),
    ("platform inventory", "GET", "/api/v1/platform/inventory", None),
    ("connections", "GET", "/api/v1/connections", None),
    ("warehouse status", "GET", "/api/v1/warehouses", None),
    ("sql review", "POST", "/api/v1/sql/review", {"sql":"SELECT * FROM raw.orders","dialect":"snowflake"}),
    ("column lineage", "POST", "/api/v1/sql/lineage", {"sql":"SELECT customer_id AS guest_id FROM raw.customers","dialect":"snowflake"}),
    ("metadata", "GET", "/api/v1/metadata/status", None),
    ("dbt manifest", "GET", "/api/v1/dbt/summary", None),
    ("airflow inventory", "GET", "/api/v1/airflow/inventory", None),
    ("airflow assets", "GET", "/api/v1/airflow/assets", None),
    ("airflow operations", "GET", "/api/v1/airflow/operations", None),
    ("quality", "GET", "/api/v1/quality/summary", None),
    ("intentional DQ failure", "POST", "/api/v1/reconciliation/row-count", {"source_value":10000,"target_value":9998,"absolute_tolerance":0,"percentage_tolerance":0}),
    ("intentional Airflow failure", "GET", "/api/v1/airflow/failure-lab", None),
    ("cross-system root cause", "POST", "/api/v1/airflow/root-cause", {"args":{"error":"Snowflake permission denied while dbt model failed"}}),
    ("data diff", "GET", "/api/v1/data-diff/demo", None),
    ("migration", "GET", "/api/v1/migration/inventory", None),
    ("finops", "GET", "/api/v1/finops/report", None),
    ("rbac", "GET", "/api/v1/rbac/audit", None),
    ("skills", "GET", "/api/v1/skills/catalog", None),
    ("training", "GET", "/api/v1/training/status", None),
    ("providers", "GET", "/api/v1/providers", None),
    ("mcp", "GET", "/api/v1/mcp/discover", None),
    ("traces", "GET", "/api/v1/traces", None),
    ("pipeline health", "GET", "/api/v1/overview", None),
]
for label, method, path, body in checks:
    response = client.request(method, path, json=body)
    if response.status_code >= 400:
        raise SystemExit(f"{label}: HTTP {response.status_code}: {response.text[:600]}")
    payload = response.json()
    if isinstance(payload, dict):
        status = payload.get("status") or payload.get("mode") or "PASS"
    else:
        status = "PASS"
    print(f"{label:28} {status}")
print("MASTER DEMO: PASS")
PY

bash scripts/demo-airflow.sh
