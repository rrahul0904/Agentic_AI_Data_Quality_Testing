from pathlib import Path

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository
from agentic_data_platform.quality.store import QualityResult, SQLiteQualityStore


ROOT = Path(__file__).resolve().parents[1]
HOSPITALITY = ROOT / "hospitality-snowflake-data-platform"


def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(HOSPITALITY))
    monkeypatch.setenv("ADE_QUALITY_DATABASE", str(tmp_path / "quality.db"))
    monkeypatch.setenv("ADE_DEMO_MODE", "true")
    return TestClient(create_app(SQLiteControlPlaneRepository(tmp_path / "control.db")))


def test_operator_overview_is_derived_from_real_project(tmp_path, monkeypatch):
    response = client(tmp_path, monkeypatch).get("/api/v1/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "LOCAL_SIMULATION"
    assert body["counts"]["oracle_tables"] == 144
    assert body["counts"]["postgres_tables"] == 157
    assert body["counts"]["file_feeds"] == 18
    assert body["counts"]["sources"] == 319
    assert body["counts"]["airflow_dags"] == 55
    assert body["counts"]["dbt_models"] == 70
    assert body["counts"]["tools"] >= 50
    assert 0 <= body["health_score"] <= 100


def test_operator_lineage_and_impact_use_real_graph(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    lineage = api.get("/api/v1/lineage/fact_reservation")
    assert lineage.status_code == 200
    assert lineage.json()["asset"]["name"] == "fact_reservation"
    impact = api.get("/api/v1/impact/stg_oracle_reservation")
    assert impact.status_code == 200
    assert impact.json()["changed_asset"]["name"] == "stg_oracle_reservation"
    assert impact.json()["downstream"]


def test_operator_sql_workspace_returns_findings_and_lineage(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    sql = "SELECT * FROM orders o CROSS JOIN customers c"
    review = api.post("/api/v1/sql/review", json={"sql": sql, "dialect": "snowflake"})
    assert review.status_code == 200
    assert review.json()["findings"]
    lineage = api.post("/api/v1/sql/lineage", json={"sql": "SELECT o.id AS order_id FROM orders o", "dialect": "snowflake"})
    assert lineage.status_code == 200
    assert lineage.json()


def test_reconciliation_demo_proves_fail_and_pass(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    failed = api.post("/api/v1/reconciliation/row-count", json={"source_value": 10000, "target_value": 9998})
    passed = api.post("/api/v1/reconciliation/row-count", json={"source_value": 10000, "target_value": 10000})
    assert failed.json()["status"] == "FAIL"
    assert passed.json()["status"] == "PASS"


def test_quality_store_summary_and_history(tmp_path, monkeypatch):
    database = tmp_path / "quality.db"
    monkeypatch.setenv("ADE_QUALITY_DATABASE", str(database))
    store = SQLiteQualityStore(database)
    store.initialize()
    run_id = store.start_run("demo")
    store.save_result(QualityResult(
        check_id="reservation_pk_unique",
        run_id=run_id,
        system="snowflake",
        layer="RAW",
        asset="RAW.ORACLE_RESERVATION",
        check_type="duplicate_key",
        severity="ERROR",
        status="FAIL",
        observed_value=2,
        expected_value=0,
    ))
    store.save_reconciliation(run_id, {
        "metric": "row_count", "source_value": 10000, "target_value": 9998, "difference": 2, "status": "FAIL"
    })
    store.complete_run(run_id, "FAIL")

    api = client(tmp_path, monkeypatch)
    summary = api.get("/api/v1/quality/summary").json()
    assert summary["run_count"] == 1
    assert summary["status_counts"]["FAIL"] == 1
    assert summary["reconciliation_status_counts"]["FAIL"] == 1


def test_operator_dbt_airflow_migration_and_warehouse_contracts(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    coverage = api.get("/api/v1/dbt/coverage")
    assert coverage.status_code == 200 and coverage.json()["models"] == 70
    airflow = api.get("/api/v1/airflow/inventory")
    assert airflow.status_code == 200 and airflow.json()["dag_count"] == 55
    assert len(airflow.json()["details"]) == 55
    migration = api.get("/api/v1/migration/inventory")
    assert migration.status_code == 200 and migration.json()["models"] >= 1
    warehouses = api.get("/api/v1/warehouses")
    assert warehouses.status_code == 200 and len(warehouses.json()["adapters"]) == 7


def test_deterministic_agent_reports_tool_evidence(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    response = api.post("/api/v1/agent/query", json={"question": "What depends on stg_oracle_reservation?"})
    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["tools_used"] == ["platform_impact"]
    assert body["result"]["changed_asset"]["name"] == "stg_oracle_reservation"
