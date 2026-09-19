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
    assert len(command_text) == 9
    assert any("generate_data.py" in command for command in command_text)
    assert any("validate_dataset.py" in command for command in command_text)
    assert any("generate_change_events.py" in command for command in command_text)
    assert any("generate_snowflake_ddl.py" in command for command in command_text)
    assert any("generate_load_sql.py" in command for command in command_text)
    assert any("generate_cdc_apply_sql.py" in command for command in command_text)
    assert any("generate_dbt_project.py" in command for command in command_text)
    assert any("build_semantic_release.py" in command for command in command_text)
    assert any("generate_airflow_dag.py" in command for command in command_text)
    assert plan["paths"]["release"].endswith("/release")
    assert plan["paths"]["cdc"].endswith("/cdc")
    assert plan["cdc_events_per_type"] == 5


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
    assert any("system_execute_sql" in item for item in result["acceptance"])
    assert any("canonical signature" in item for item in result["acceptance"])


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
    assert plan["benchmark"]["requires_agent_result_parity"] is True
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


def test_agent_benchmark_parity_passes_when_value_signatures_match(tmp_path: Path):
    report_path = tmp_path / "benchmark.json"
    report_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "status": "PASS",
                        "query_name": "q1",
                        "variant": "direct",
                        "value_sha256": "same-values",
                    },
                    {
                        "status": "PASS",
                        "query_name": "q1",
                        "variant": "semantic",
                        "value_sha256": "same-values",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    agent = {
        "results": [
            {
                "business_query_id": "q1",
                "analytical_executions": [
                    {
                        "status": "success",
                        "query_id": "agent-query-1",
                        "result_signature": {"value_sha256": "same-values"},
                    }
                ],
            }
        ]
    }
    parity = cli.agent_benchmark_parity(agent, [report_path])
    assert parity["status"] == "PASS"
    assert parity["failed_queries"] == 0
    assert parity["queries"]["q1"]["agent_query_ids"] == ["agent-query-1"]


def test_agent_benchmark_parity_fails_on_ai_result_drift(tmp_path: Path):
    report_path = tmp_path / "benchmark.json"
    report_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "status": "PASS",
                        "query_name": "q1",
                        "variant": "direct",
                        "value_sha256": "canonical-values",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    agent = {
        "results": [
            {
                "business_query_id": "q1",
                "analytical_executions": [
                    {
                        "status": "success",
                        "query_id": "agent-query-2",
                        "result_signature": {"value_sha256": "different-values"},
                    }
                ],
            }
        ]
    }
    parity = cli.agent_benchmark_parity(agent, [report_path])
    assert parity["status"] == "FAIL"
    assert parity["failed_queries"] == 1
    assert "differs" in parity["queries"]["q1"]["reason"]


def test_consumer_parity_plan_lists_expected_evidence(tmp_path: Path):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    manifest = {
        "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
        "cases": [
            {
                "id": "q1",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
                "acceptance": {
                    "numeric_tolerance": 1e-9,
                    "same_security_context": True,
                    "require_captured_evidence": True,
                    "allow_empty_result": False,
                },
            }
        ],
    }
    (parity_dir / "parity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence_dir = workspace / "external-evidence"
    evidence_dir.mkdir()
    (evidence_dir / "q1.snowflake_semantic_view.json").write_text("{}", encoding="utf-8")

    plan = cli.consumer_parity_plan(workspace, evidence_dir)
    assert plan["expected_evidence_count"] == 4
    assert plan["present_evidence_count"] == 1
    assert plan["missing_evidence_count"] == 3
    assert plan["evidence_contract"]["capture_status"] == "CAPTURED"
    assert plan["evidence_contract"]["non_empty_rows_required"] is True


def test_certify_consumers_passes_complete_captured_evidence(tmp_path: Path):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    consumers = ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"]
    manifest = {
        "required_consumers": consumers,
        "cases": [
            {
                "id": "q1",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
                "acceptance": {
                    "numeric_tolerance": 1e-9,
                    "same_security_context": True,
                    "require_captured_evidence": True,
                    "allow_empty_result": False,
                },
            }
        ],
    }
    (parity_dir / "parity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence_dir = workspace / "external-evidence"
    evidence_dir.mkdir()
    for consumer in consumers:
        payload = {
            "case_id": "q1",
            "consumer": consumer,
            "security_context": "ROLE_ANALYST",
            "capture_status": "CAPTURED",
            "rows": [{"DIMENSION_A": "A", "METRIC_A": 10.0}],
        }
        (evidence_dir / f"q1.{consumer}.json").write_text(json.dumps(payload), encoding="utf-8")

    report = cli.certify_consumers(workspace, evidence_dir=evidence_dir)
    assert report["status"] == "PASS"
    assert report["failed_cases"] == 0
    assert report["expected_evidence_count"] == 4
    assert Path(report["report"]).exists()


def test_prepare_consumer_evidence_writes_pending_templates_without_overwrite(tmp_path: Path):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    manifest = {
        "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
        "cases": [
            {
                "id": "q1",
                "business_question": "What is metric A?",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
                "acceptance": {
                    "numeric_tolerance": 1e-9,
                    "same_security_context": True,
                    "require_captured_evidence": True,
                    "allow_empty_result": False,
                },
            }
        ],
    }
    (parity_dir / "parity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence_dir = workspace / "external-evidence"

    first = cli.prepare_consumer_evidence(
        workspace,
        evidence_dir=evidence_dir,
        security_context="ROLE_ANALYST",
    )
    assert first["status"] == "PASS"
    assert first["written_count"] == 4
    assert first["skipped_count"] == 0

    sample = json.loads((evidence_dir / "q1.power_bi.json").read_text(encoding="utf-8"))
    assert sample["capture_status"] == "PENDING"
    assert sample["security_context"] == "ROLE_ANALYST"
    assert sample["rows"] == []
    assert sample["expected_metrics"] == ["METRIC_A"]
    assert "without local metric reimplementation" in sample["capture_instructions"]

    second = cli.prepare_consumer_evidence(
        workspace,
        evidence_dir=evidence_dir,
        security_context="ROLE_ANALYST",
    )
    assert second["written_count"] == 0
    assert second["skipped_count"] == 4

    report = cli.certify_consumers(workspace, evidence_dir=evidence_dir)
    assert report["status"] == "FAIL"
    assert any(
        "capture_status must be CAPTURED" in error
        for result in report["results"]
        for error in result["errors"]
    )


def test_governed_evidence_plan_targets_only_snowflake_and_agent(tmp_path: Path):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    manifest = {
        "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
        "cases": [
            {
                "id": "q1",
                "business_question": "What is metric A?",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
                "reference": {"sql_file": "q1.reference.sql"},
            }
        ],
    }
    (parity_dir / "parity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    plan = cli.governed_evidence_plan(
        workspace,
        evidence_dir=workspace / "external-evidence",
        security_context="ROLE_ANALYST",
        max_rows=100,
    )
    assert plan["case_count"] == 1
    assert plan["captured_consumers"] == ["snowflake_semantic_view", "cortex_agent_mcp"]
    assert plan["external_consumers_remaining"] == ["power_bi", "excel"]
    assert plan["cases"][0]["expected_columns"] == ["DIMENSION_A", "METRIC_A"]


def test_agent_consumer_evidence_writes_captured_rows_for_exact_columns(tmp_path: Path):
    manifest = {
        "cases": [
            {
                "id": "q1",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
            }
        ]
    }
    agent_report = {
        "results": [
            {
                "business_query_id": "q1",
                "wrapper_query_id": "wrapper-1",
                "analytical_executions": [
                    {
                        "status": "success",
                        "query_id": "agent-q1",
                        "sql": "select ...",
                        "result_rows": {
                            "columns": ["DIMENSION_A", "METRIC_A"],
                            "rows": [{"DIMENSION_A": "A", "METRIC_A": "10"}],
                            "truncated": False,
                        },
                    }
                ],
            }
        ]
    }
    evidence_dir = tmp_path / "evidence"
    report = cli.agent_consumer_evidence(
        manifest,
        agent_report,
        evidence_dir=evidence_dir,
        security_context="ROLE_ANALYST",
    )
    assert report["status"] == "PASS"
    assert report["passed"] == 1
    payload = json.loads((evidence_dir / "q1.cortex_agent_mcp.json").read_text(encoding="utf-8"))
    assert payload["capture_status"] == "CAPTURED"
    assert payload["security_context"] == "ROLE_ANALYST"
    assert payload["analytical_query_id"] == "agent-q1"
    assert payload["rows"] == [{"DIMENSION_A": "A", "METRIC_A": "10"}]


def test_agent_consumer_evidence_rejects_wrong_columns_or_truncation(tmp_path: Path):
    manifest = {
        "cases": [
            {
                "id": "q1",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
            }
        ]
    }
    agent_report = {
        "results": [
            {
                "business_query_id": "q1",
                "analytical_executions": [
                    {
                        "status": "success",
                        "query_id": "agent-q1",
                        "result_rows": {
                            "columns": ["WRONG_COLUMN"],
                            "rows": [{"WRONG_COLUMN": "10"}],
                            "truncated": False,
                        },
                    },
                    {
                        "status": "success",
                        "query_id": "agent-q2",
                        "result_rows": {
                            "columns": ["DIMENSION_A", "METRIC_A"],
                            "rows": [{"DIMENSION_A": "A", "METRIC_A": "10"}],
                            "truncated": True,
                        },
                    },
                ],
            }
        ]
    }
    report = cli.agent_consumer_evidence(
        manifest,
        agent_report,
        evidence_dir=tmp_path / "evidence",
        security_context="ROLE_ANALYST",
    )
    assert report["status"] == "FAIL"
    assert report["failed"] == 1
    assert "expected columns" in report["results"][0]["error"]


def test_consumer_parity_plan_counts_captured_pending_and_invalid(tmp_path: Path):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    manifest = {
        "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
        "cases": [{"id": "q1"}],
    }
    (parity_dir / "parity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "q1.snowflake_semantic_view.json").write_text(
        json.dumps({"capture_status": "CAPTURED"}),
        encoding="utf-8",
    )
    (evidence_dir / "q1.cortex_agent_mcp.json").write_text(
        json.dumps({"capture_status": "PENDING"}),
        encoding="utf-8",
    )
    (evidence_dir / "q1.power_bi.json").write_text("{bad json", encoding="utf-8")

    plan = cli.consumer_parity_plan(workspace, evidence_dir)
    assert plan["expected_evidence_count"] == 4
    assert plan["captured_evidence_count"] == 1
    assert plan["pending_evidence_count"] == 1
    assert plan["invalid_evidence_count"] == 1
    assert plan["missing_evidence_count"] == 1


def test_capture_governed_evidence_dry_run_needs_no_credentials(tmp_path: Path):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    manifest = {
        "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
        "cases": [
            {
                "id": "q1",
                "business_question": "What is metric A?",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
                "reference": {"sql_file": "q1.reference.sql"},
            }
        ],
    }
    (parity_dir / "parity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = cli.capture_governed_evidence(
        workspace,
        evidence_dir=tmp_path / "evidence",
        security_context="ROLE_ANALYST",
        max_rows=500,
        confirm=False,
        dry_run=True,
    )
    assert result["status"] == "DRY_RUN"
    assert result["max_rows"] == 500
    assert result["external_consumers_remaining"] == ["power_bi", "excel"]


def test_capture_governed_evidence_requires_explicit_matching_role(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "demo"
    parity_dir = workspace / "release" / "parity"
    parity_dir.mkdir(parents=True)
    (parity_dir / "parity_manifest.json").write_text(
        json.dumps(
            {
                "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("SNOWFLAKE_ROLE", raising=False)
    try:
        cli.capture_governed_evidence(
            workspace,
            evidence_dir=tmp_path / "evidence",
            security_context="ROLE_ANALYST",
            confirm=True,
        )
    except RuntimeError as exc:
        assert "SNOWFLAKE_ROLE must be explicitly set" in str(exc)
    else:
        raise AssertionError("governed evidence capture must bind to an explicit Snowflake role")


def test_cdc_plan_requires_generated_change_assets(tmp_path: Path):
    workspace = tmp_path / "demo"
    required = [
        workspace / "cdc" / "manifest.json",
        workspace / "cdc" / "change_events.jsonl",
        workspace / "snowflake" / "003_apply_cdc.sql",
        workspace / "dbt" / "dbt_project.yml",
        workspace / "release" / "semantic" / "verify_semantic_view.sql",
    ]
    for path in required[:-1]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    plan = cli.cdc_plan(workspace)
    assert plan["workspace_ready"] is False
    assert plan["required_artifacts"]["semantic_verify"]["exists"] is False

    required[-1].parent.mkdir(parents=True, exist_ok=True)
    required[-1].write_text("-- verify", encoding="utf-8")
    plan = cli.cdc_plan(workspace)
    assert plan["workspace_ready"] is True
    assert "execute idempotent CDC MERGE SQL" in plan["steps"]


def test_apply_cdc_dry_run_is_safe_without_credentials(tmp_path: Path):
    workspace = tmp_path / "demo"
    result = cli.apply_cdc(
        workspace,
        confirm=False,
        dry_run=True,
        verify_idempotency=True,
    )
    assert result["status"] == "DRY_RUN"
    assert result["verify_idempotency"] is True
    assert result["workspace_ready"] is False


def test_apply_cdc_refuses_live_execution_without_confirm(tmp_path: Path):
    try:
        cli.apply_cdc(
            tmp_path,
            confirm=False,
            dry_run=False,
            verify_idempotency=False,
        )
    except RuntimeError as exc:
        assert "without --confirm" in str(exc)
    else:
        raise AssertionError("live CDC application must be fail-closed")
