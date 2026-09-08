from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app


def test_airflow_full_surface_routes(tmp_path, monkeypatch):
    dags = tmp_path / "airflow" / "dags"
    dags.mkdir(parents=True)
    (dags / "example.py").write_text(
        "from airflow.sdk import DAG, Asset\n"
        "asset = Asset('s3://landing/test')\n"
        "dag = DAG(dag_id='example', schedule=asset, catchup=False)\n"
    )
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    client = TestClient(create_app())

    for path in (
        "/api/v1/airflow/dags",
        "/api/v1/airflow/dags/example",
        "/api/v1/airflow/dags/example/tasks",
        "/api/v1/airflow/assets",
        "/api/v1/airflow/connections",
        "/api/v1/airflow/pools",
        "/api/v1/airflow/import-errors",
        "/api/v1/airflow/capacity",
        "/api/v1/airflow/upgrade",
        "/api/v1/airflow/security",
        "/api/v1/airflow/xcom",
        "/api/v1/airflow/bundles",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)

    runtime = client.get("/api/v1/airflow/dags/example/runs")
    assert runtime.status_code == 200
    assert runtime.json()["status"] == "SKIP_EXTERNAL"

    plan = client.post(
        "/api/v1/airflow/backfill/plan",
        json={"args": {"dag_id": "example", "start_date": "2026-09-01", "end_date": "2026-09-03"}},
    )
    assert plan.status_code == 200
    assert plan.json()["mode"] == "DRY_RUN"
    assert plan.json()["execution_allowed"] is False
