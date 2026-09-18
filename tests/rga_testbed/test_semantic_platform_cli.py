from __future__ import annotations

import json
from pathlib import Path

from agentic_data_platform import semantic_platform_cli as cli


def test_about_basis_is_product_not_rga_generator():
    basis = cli.PRODUCT_BASIS
    assert "Define business semantics once" in basis["principle"]
    assert basis["runtime"] == "Snowflake Semantic Views are the governed semantic runtime."
    assert "not the product" in basis["testbed"]
    assert "Power BI" in basis["consumers"]
    assert "Excel" in basis["consumers"]
    assert "Cortex Agent/MCP" in basis["consumers"]


def test_readiness_is_fail_closed_without_live_credentials(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "rga_semantic_contract.yml").write_text("x", encoding="utf-8")
    (repo / "config" / "rga_domain.yml").write_text("x", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "rga-synthetic-data.yml").write_text("name: x", encoding="utf-8")

    status = cli.readiness_status(env={}, repo_root=repo, release_dir=repo / "release")
    assert status["status"] == "READY_FOR_LOCAL_BUILD"
    assert status["external"]["snowflake_live_ready"] is False
    assert "SNOWFLAKE_ACCOUNT" in status["external"]["snowflake_missing"]
    assert status["external"]["power_bi_excel_live_parity_ready"] is False


def test_demo_plan_builds_complete_operator_sequence(tmp_path: Path):
    plan = cli.demo_plan(
        tmp_path / "demo",
        preset="tiny",
        seed=7,
        policies=120,
        database="RGA_SYNTHETIC_TESTBED",
    )
    command_text = [" ".join(command) for command in plan["commands"]]
    assert len(command_text) == 7
    assert any("generate_data.py" in command for command in command_text)
    assert any("validate_dataset.py" in command for command in command_text)
    assert any("generate_snowflake_ddl.py" in command for command in command_text)
    assert any("generate_load_sql.py" in command for command in command_text)
    assert any("generate_dbt_project.py" in command for command in command_text)
    assert any("build_semantic_release.py" in command for command in command_text)
    assert any("generate_airflow_dag.py" in command for command in command_text)
    assert plan["paths"]["release"].endswith("/release")


def test_snowflake_demo_refuses_without_confirm(tmp_path: Path):
    try:
        cli.snowflake_demo(tmp_path, confirm=False, deploy_semantic=False, deploy_ai=False)
    except RuntimeError as exc:
        assert "without --confirm" in str(exc)
    else:
        raise AssertionError("live Snowflake demo must be fail-closed")


def test_cli_about_returns_json(capsys):
    assert cli.main(["about"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime"] == "Snowflake Semantic Views are the governed semantic runtime."


def test_cli_status_returns_json(capsys):
    assert cli.main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "local" in payload
    assert "external" in payload
    assert "boundaries" in payload
