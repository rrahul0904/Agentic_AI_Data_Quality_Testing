from pathlib import Path
import subprocess

from agentic_data_platform.platform.discovery import PlatformDiscovery, render_discovery


def test_zero_config_discovery_handles_plain_repository(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "query.sql").write_text("select 1")
    result = PlatformDiscovery(tmp_path).discover()
    assert result["git"]["found"] is True
    assert result["dbt"]["found"] is False
    assert result["sql"]["sqlglot_compatible"] is True
    assert all("password" not in str(item).casefold() for item in result["warehouses"])
    rendered = render_discovery(result)
    assert "Agentic Project Discovery" in rendered
    assert "credentials: values redacted" in rendered


def test_discovery_detects_minimal_dbt_project(tmp_path: Path):
    dbt = tmp_path / "dbt"
    (dbt / "models").mkdir(parents=True)
    (dbt / "dbt_project.yml").write_text("name: analytics\nprofile: analytics\nmodel-paths: ['models']\n")
    (dbt / "models" / "orders.sql").write_text("select 1 as id")
    result = PlatformDiscovery(tmp_path).discover()
    assert result["dbt"]["found"] is True
    assert result["dbt"]["project_name"] == "analytics"
    assert result["dbt"]["models"] == 1


def test_discovery_detects_airflow_project(tmp_path: Path):
    dags = tmp_path / "airflow" / "dags"
    dags.mkdir(parents=True)
    (dags / "orders.py").write_text(
        "from airflow import DAG\n"
        "from airflow.datasets import Dataset\n"
        "orders = Dataset('snowflake://orders')\n"
        "with DAG('orders_pipeline', schedule=None) as dag:\n"
        "    pass\n"
    )
    result = PlatformDiscovery(tmp_path).discover()
    assert result["airflow"]["found"] is True
    assert result["airflow"]["dag_count"] >= 1
    assert result["airflow"]["datasets_detected"] >= 1


def test_discovery_handles_dbt_airflow_monorepo(tmp_path: Path):
    dbt = tmp_path / "analytics"
    (dbt / "models").mkdir(parents=True)
    (dbt / "dbt_project.yml").write_text("name: monorepo_analytics\nprofile: monorepo\n")
    (dbt / "models" / "orders.sql").write_text("select 1 as id")
    dags = tmp_path / "airflow" / "dags"
    dags.mkdir(parents=True)
    (dags / "pipeline.py").write_text("from airflow import DAG\nwith DAG('monorepo_pipeline', schedule=None) as dag:\n    pass\n")
    result = PlatformDiscovery(tmp_path).discover()
    assert result["dbt"]["found"] is True
    assert result["dbt"]["project_name"] == "monorepo_analytics"
    assert result["airflow"]["found"] is True


def test_discovery_reports_multiple_warehouse_hints_without_values(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ADE_SNOWFLAKE_ACCOUNT", "secret-account")
    monkeypatch.setenv("ADE_POSTGRES_DSN", "postgresql://user:password@example/db")
    monkeypatch.setenv("ADE_DATABRICKS_HOST", "https://workspace.example")
    result = PlatformDiscovery(tmp_path).discover()
    detected = {item["warehouse"] for item in result["warehouses"] if item["configuration_detected"]}
    assert {"snowflake", "postgres", "databricks"}.issubset(detected)
    rendered = render_discovery(result)
    assert "secret-account" not in rendered
    assert "password@example" not in rendered
    assert all(item["credential_values_exposed"] is False for item in result["warehouses"])


def test_discovery_handles_empty_directory(tmp_path: Path):
    result = PlatformDiscovery(tmp_path).discover()
    assert result["git"]["found"] is False
    assert result["dbt"]["found"] is False
    assert result["airflow"]["found"] is False
    assert result["sql"]["sqlglot_compatible"] is True


def test_discovery_handles_broken_dbt_configuration_without_crashing(tmp_path: Path):
    dbt = tmp_path / "dbt"
    (dbt / "models").mkdir(parents=True)
    (dbt / "dbt_project.yml").write_text("name: [broken\nprofile: ???:\n")
    (dbt / "profiles.yml").write_text("broken: [yaml\n")
    (dbt / "models" / "orders.sql").write_text("select 1 as id")
    result = PlatformDiscovery(tmp_path).discover()
    assert result["dbt"]["found"] is True
    assert result["dbt"]["project_name"] is None
    assert result["dbt"]["models"] == 1
