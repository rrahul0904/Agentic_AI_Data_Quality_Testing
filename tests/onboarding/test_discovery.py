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
