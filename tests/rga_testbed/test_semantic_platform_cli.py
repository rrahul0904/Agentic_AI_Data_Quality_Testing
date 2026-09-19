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


def test_parse_concurrency_sweep_deduplicates_and_sorts():
    assert cli.parse_concurrency_sweep("10,1,5,10") == [1, 5, 10]


def test_parse_concurrency_sweep_rejects_invalid_values():
    try:
        cli.parse_concurrency_sweep("1,0,101")
    except ValueError as exc:
        assert "between 1 and 100" in str(exc)
    else:
        raise AssertionError("invalid concurrency sweep should be rejected")


def test_live_certification_dry_run_exposes_complete_plan(tmp_path: Path):
    workspace = tmp_path / "demo"
    required = [
        workspace / "data" / "manifest.json",
        workspace / "snowflake" / "001_raw_tables.sql",
        workspace / "snowflake" / "002_load_raw.sql",
        workspace / "dbt" / "dbt_project.yml",
        workspace / "release" / "release_manifest.json",
        workspace / "release" / "semantic" / "verify_semantic_view.sql",
        workspace / "release" / "semantic" / "deploy_semantic_view.sql",
        workspace / "release" / "benchmarks" / "manifest.json",
    ]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    result = cli.certify_live(
        workspace,
        confirm=False,
        dry_run=True,
        concurrency=[1, 5, 10],
        iterations=2,
        deploy_ai=False,
    )
    assert result["status"] == "DRY_RUN"
    assert result["workspace_ready"] is True
    assert result["benchmark"]["concurrency"] == [1, 5, 10]
    assert result["benchmark"]["requires_result_parity"] is True
    assert result["benchmark"]["requires_query_history_telemetry"] is True
    assert result["deployment"]["deploy_semantic_view"] is True


def test_live_certification_refuses_without_confirm(tmp_path: Path):
    try:
        cli.certify_live(
            tmp_path,
            confirm=False,
            dry_run=False,
            concurrency=[1],
            iterations=1,
            deploy_ai=False,
        )
    except RuntimeError as exc:
        assert "without --confirm" in str(exc)
    else:
        raise AssertionError("live certification must be fail-closed")


def test_agent_smoke_cli_dry_run_uses_workspace_database(tmp_path: Path):
    workspace = tmp_path / "demo"
    release = workspace / "release"
    release.mkdir(parents=True)
    (release / "release_manifest.json").write_text(
        json.dumps({"database": "CUSTOM_RGA_DB"}),
        encoding="utf-8",
    )
    result = cli.agent_smoke(
        workspace,
        confirm=False,
        dry_run=True,
    )
    assert result["status"] == "DRY_RUN"
    assert result["agent"] == "CUSTOM_RGA_DB.AI.RGA_REINSURANCE_AGENT"
    assert result["task_count"] >= 3
    assert any("Reinsurance_Analyst" in item for item in result["acceptance"])


def test_certification_plan_requires_ai_artifacts_when_ai_is_enabled(tmp_path: Path):
    workspace = tmp_path / "demo"
    common = [
        workspace / "data" / "manifest.json",
        workspace / "snowflake" / "001_raw_tables.sql",
        workspace / "snowflake" / "002_load_raw.sql",
        workspace / "dbt" / "dbt_project.yml",
        workspace / "release" / "release_manifest.json",
        workspace / "release" / "semantic" / "verify_semantic_view.sql",
        workspace / "release" / "semantic" / "deploy_semantic_view.sql",
        workspace / "release" / "benchmarks" / "manifest.json",
    ]
    for path in common:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    plan = cli.certification_plan(
        workspace,
        concurrency=[1],
        iterations=1,
        deploy_ai=True,
    )
    assert plan["workspace_ready"] is False
    assert plan["deployment"]["agent_runtime_smoke"] is True
    assert "agent_create" in plan["required_artifacts"]
    assert "mcp_create" in plan["required_artifacts"]

    for path in (
        workspace / "release" / "ai" / "create_agent.sql",
        workspace / "release" / "ai" / "create_mcp_server.sql",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("-- generated", encoding="utf-8")

    plan = cli.certification_plan(
        workspace,
        concurrency=[1],
        iterations=1,
        deploy_ai=True,
    )
    assert plan["workspace_ready"] is True
    assert plan["evidence"]["agent_smoke"].endswith("agent_smoke.json")
