from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentic_data_platform.advanced_capabilities import (
    EmbeddedAgentSession,
    agent_recovery_execute,
    agent_recovery_plan,
    account_admin_plan,
    anomaly_compare,
    audited_web_fetch,
    audited_web_search,
    apply_file_edit,
    apply_region_edit,
    build_chart_spec,
    command_plan,
    compare_document_extractions,
    document_extract,
    forecast_series,
    git_change_apply,
    git_change_plan,
    git_status,
    gpu_job_plan,
    gpu_job_run,
    immutable_plan,
    list_agent_definitions,
    mode_contract,
    plan_file_edit,
    plan_region_edit,
    retrieval_search,
    route_model_for_mode,
    run_command,
    sdk_contract,
    save_agent_definition,
    search_warehouse_objects,
    select_context,
    snowflake_document_extract_plan,
    snowflake_document_parse_plan,
    sql_playground,
    verify_immutable_plan,
)


def test_mode_contracts_enforce_ask_plan_edit_and_code_boundaries() -> None:
    ask = mode_contract("ask")
    plan = mode_contract("plan")
    code = mode_contract("code", budget_usd=0.25)
    edit = mode_contract("edit")

    assert ask["purpose"] == "question_answer_exploration"
    assert ask["actor_mode"] == "ask"
    assert ask["workspace_mutations"] is False
    assert ask["data_mutations"] is False
    assert ask["implementation_plan_required"] is False
    assert "file_mutation" in ask["denied_tool_categories"]
    assert plan["purpose"] == "implementation_research_and_structured_plan"
    assert plan["workspace_mutations"] is False
    assert plan["data_mutations"] is False
    assert "ordered_implementation_steps" in plan["output_contract"]
    assert code["data_mutations"] is False
    assert code["model_policy"] == "lowest_cost_capable_model"
    assert "snowflake_data_tools" in code["denied_tool_categories"]
    assert "mcp" in code["denied_tool_categories"]
    assert "git" in code["allowed_tool_categories"]
    assert edit["workspace_mutations"] == "hash_bound_approval"
    assert edit["purpose"] == "selected_region_edit"
    assert plan["contract_fingerprint"]


def test_immutable_plan_detects_tampering() -> None:
    plan = immutable_plan(
        [{"tool": "semantic_search", "args": {"query": "revenue"}}],
        constraints={"max_cost_usd": 1.0},
        verification=[{"check": "result_fingerprint"}],
    )
    assert verify_immutable_plan(plan)["status"] == "PASS"

    tampered = dict(plan)
    tampered["steps"] = [{"tool": "snowflake_mutation_execute"}]
    assert verify_immutable_plan(tampered)["status"] == "STALE_PLAN"


def test_hash_bound_file_edit_rolls_back_on_failed_verification(tmp_path) -> None:
    target = tmp_path / "model.sql"
    target.write_text("select 1\n", encoding="utf-8")
    plan = plan_file_edit(
        tmp_path,
        "model.sql",
        "select 2\n",
        verification_command=[sys.executable, "-c", "raise SystemExit(7)"],
    )
    result = apply_file_edit(
        tmp_path,
        "model.sql",
        "select 2\n",
        approval_fingerprint=plan["approval_fingerprint"],
        verification_command=[sys.executable, "-c", "raise SystemExit(7)"],
    )
    assert result["status"] == "VERIFICATION_FAILED_ROLLED_BACK"
    assert target.read_text(encoding="utf-8") == "select 1\n"


def test_hash_bound_file_edit_passes_and_verifies_exact_hash(tmp_path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("old", encoding="utf-8")
    plan = plan_file_edit(tmp_path, "notes.md", "new")
    result = apply_file_edit(
        tmp_path,
        "notes.md",
        "new",
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert result["status"] == "PASS"
    assert target.read_text(encoding="utf-8") == "new"
    assert result["result_hash"] == plan["result_hash"]


def test_file_edit_stale_approval_is_never_overwritten_by_plan_status(tmp_path) -> None:
    target = tmp_path / "approval.txt"
    target.write_text("before", encoding="utf-8")
    result = apply_file_edit(
        tmp_path,
        "approval.txt",
        "after",
        approval_fingerprint="definitely-not-the-plan-fingerprint",
    )
    assert result["status"] == "STALE_APPROVAL"
    assert target.read_text(encoding="utf-8") == "before"


def test_file_edit_rejects_workspace_escape(tmp_path) -> None:
    with pytest.raises(ValueError):
        plan_file_edit(tmp_path, "../escape.txt", "nope")


def test_selected_region_edit_changes_only_requested_lines(tmp_path) -> None:
    target = tmp_path / "retry.py"
    original = "before\none\ntwo\nafter\n"
    target.write_text(original, encoding="utf-8")
    plan = plan_region_edit(tmp_path, "retry.py", 2, 3, "ONE\nTWO\n")

    assert plan["status"] == "PASS"
    assert plan["selected_text_hash"]
    assert "@@" in plan["diff"]

    result = apply_region_edit(
        tmp_path,
        "retry.py",
        2,
        3,
        "ONE\nTWO\n",
        approval_fingerprint=plan["approval_fingerprint"],
        expected_source_hash=plan["source_file_hash"],
        expected_selected_hash=plan["selected_text_hash"],
    )

    assert result["status"] == "PASS"
    assert target.read_text(encoding="utf-8") == "before\nONE\nTWO\nafter\n"
    assert target.read_text(encoding="utf-8").startswith("before\n")
    assert target.read_text(encoding="utf-8").endswith("after\n")
    assert result["result_file_hash"] == plan["result_file_hash"]


def test_selected_region_edit_rejects_stale_source_selection_and_approval(tmp_path) -> None:
    target = tmp_path / "selection.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    plan = plan_region_edit(tmp_path, "selection.txt", 2, 2, "BETA\n")
    assert plan["status"] == "PASS"

    stale_approval = apply_region_edit(
        tmp_path,
        "selection.txt",
        2,
        2,
        "BETA\n",
        approval_fingerprint="tampered",
    )
    assert stale_approval["status"] == "STALE_APPROVAL"
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"

    target.write_text("alpha\nchanged\ngamma\n", encoding="utf-8")
    stale_source = apply_region_edit(
        tmp_path,
        "selection.txt",
        2,
        2,
        "BETA\n",
        approval_fingerprint=plan["approval_fingerprint"],
        expected_source_hash=plan["source_file_hash"],
    )
    assert stale_source["status"] == "STALE_SOURCE"

    current = plan_region_edit(tmp_path, "selection.txt", 2, 2, "BETA\n")
    stale_selection = plan_region_edit(
        tmp_path,
        "selection.txt",
        2,
        2,
        "BETA\n",
        expected_selected_hash=plan["selected_text_hash"],
    )
    assert current["status"] == "PASS"
    assert stale_selection["status"] == "STALE_SELECTION"


def test_selected_region_edit_rolls_back_when_verification_fails(tmp_path) -> None:
    target = tmp_path / "rollback.txt"
    target.write_text("keep\nold\nkeep2\n", encoding="utf-8")
    verification = [sys.executable, "-c", "raise SystemExit(9)"]
    plan = plan_region_edit(
        tmp_path,
        "rollback.txt",
        2,
        2,
        "new\n",
        verification_command=verification,
    )
    result = apply_region_edit(
        tmp_path,
        "rollback.txt",
        2,
        2,
        "new\n",
        approval_fingerprint=plan["approval_fingerprint"],
        verification_command=verification,
    )
    assert result["status"] == "VERIFICATION_FAILED_ROLLED_BACK"
    assert target.read_text(encoding="utf-8") == "keep\nold\nkeep2\n"


def test_selected_region_edit_rejects_invalid_region(tmp_path) -> None:
    target = tmp_path / "bounds.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    result = plan_region_edit(tmp_path, "bounds.txt", 2, 99, "x\n")
    assert result["status"] == "INVALID_REGION"


def test_shell_is_argv_only_bounded_and_approval_fingerprinted(tmp_path) -> None:
    plan = command_plan(
        tmp_path,
        [sys.executable, "-c", "print('ok')"],
        timeout_seconds=5,
        max_output_bytes=2048,
    )
    assert plan["status"] == "PASS"
    result = run_command(
        tmp_path,
        [sys.executable, "-c", "print('ok')"],
        timeout_seconds=5,
        max_output_bytes=2048,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert result["status"] == "PASS"
    assert result["stdout"].strip() == "ok"

    with pytest.raises(PermissionError):
        command_plan(tmp_path, ["bash", "-c", "echo bypass"])


def test_context_selection_is_ranked_and_budgeted() -> None:
    result = select_context(
        [
            {"id": "weak", "text": "x" * 400, "evidence_rank": 1, "relevance": 0.1},
            {"id": "strong", "text": "y" * 200, "evidence_rank": 3, "relevance": 0.9},
            {"id": "medium", "text": "z" * 200, "evidence_rank": 2, "relevance": 0.5},
        ],
        budget_tokens=128,
        provider="snowflake-cortex",
    )
    assert result["status"] == "PASS"
    assert result["used_tokens"] <= 128
    assert result["selected"][0]["id"] == "strong"


def test_custom_agent_definition_persists_policy_contract(tmp_path) -> None:
    saved = save_agent_definition(
        tmp_path,
        {
            "name": "warehouse-investigator",
            "model": "auto",
            "allowed_tools": ["semantic_search", "snowflake_pipeline_rca"],
            "scopes": ["project"],
            "budgets": {"max_cost_usd": 2.0, "max_tool_calls": 30},
            "verification": [{"type": "evidence_required"}],
        },
    )
    assert saved["status"] == "PASS"
    listed = list_agent_definitions(tmp_path)
    assert listed["agents"][0]["name"] == "warehouse-investigator"
    assert listed["agents"][0]["allowed_tools"] == ["semantic_search", "snowflake_pipeline_rca"]


def test_cross_warehouse_object_search_uses_lineage_and_platforms() -> None:
    result = search_warehouse_objects(
        "reservation revenue",
        [
            {
                "platform": "snowflake",
                "qualified_name": "PROD.MART.FACT_RESERVATION",
                "description": "reservation revenue fact",
                "columns": ["reservation_id", "revenue"],
                "downstream": ["MART.REVPAR"],
                "recent_evidence": True,
            },
            {
                "platform": "redshift",
                "qualified_name": "analytics.customer",
                "description": "customer dimension",
                "columns": ["customer_id"],
            },
        ],
    )
    assert result["status"] == "PASS"
    assert result["results"][0]["qualified_name"] == "PROD.MART.FACT_RESERVATION"
    assert "snowflake" in result["platforms"]


def test_sql_playground_executes_read_only_sql_and_records_provenance(tmp_path) -> None:
    database = tmp_path / "playground.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("create table sales(day text, revenue integer)")
        connection.executemany("insert into sales values (?, ?)", [("Mon", 10), ("Tue", 20)])
        connection.commit()
    finally:
        connection.close()

    result = sql_playground(
        "select day, revenue from sales order by day",
        dialect="sqlite",
        sqlite_database=str(database),
    )
    assert result["status"] == "PASS"
    assert result["execution"] == "PASS"
    assert result["lineage"]["tables"] == ["sales"]
    assert result["row_count_returned"] == 2
    assert result["result_fingerprint"]

    blocked = sql_playground("delete from sales", dialect="sqlite", sqlite_database=str(database))
    assert blocked["status"] == "BLOCKED_POLICY"


def test_inline_chart_carries_query_result_and_replay_provenance() -> None:
    rows = [{"day": "Mon", "revenue": 10}, {"day": "Tue", "revenue": 20}]
    chart = build_chart_spec(
        rows,
        kind="line",
        x="day",
        y="revenue",
        source_query="select day, revenue from sales",
        warehouse="snowflake",
    )
    assert chart["status"] == "PASS"
    assert chart["provenance"]["query_fingerprint"]
    assert chart["provenance"]["result_fingerprint"]
    assert chart["replay"]["warehouse"] == "snowflake"


def test_forecast_compares_baselines_and_stores_evaluation_evidence() -> None:
    result = forecast_series([10, 11, 12, 13, 14, 15, 16, 17], horizon=3)
    assert result["status"] == "PASS"
    assert len(result["forecast"]) == 3
    assert result["winner"] in {"linear_trend", "moving_average"}
    assert "linear_trend_mae" in result["evaluation"]
    assert result["evaluation_fingerprint"]


def test_anomaly_compare_uses_two_independent_detectors() -> None:
    result = anomaly_compare([10, 10, 11, 10, 9, 10, 100], z_threshold=2.0, mad_threshold=3.0)
    assert result["status"] == "PASS"
    assert 6 in result["detectors"]["zscore"]
    assert 6 in result["detectors"]["mad"]
    assert 6 in result["detectors"]["trend_residual"]
    assert 6 in result["consensus"]
    assert result["detector_types"]["trend_residual"] == "model_based"


def test_document_intelligence_extracts_fields_chunks_and_cost_evidence(tmp_path) -> None:
    doc = tmp_path / "invoice.txt"
    doc.write_text("Invoice: INV-42\nTotal: $123.45\nCustomer: Acme", encoding="utf-8")
    result = document_extract(
        tmp_path,
        "invoice.txt",
        fields={
            "invoice_id": r"Invoice:\s*(\S+)",
            "total": r"Total:\s*\$([0-9.]+)",
        },
        chunk_chars=256,
    )
    assert result["status"] == "PASS"
    assert result["fields"]["invoice_id"] == "INV-42"
    assert result["fields"]["total"] == "123.45"
    assert result["text_sha256"]
    assert result["chunks"][0]["sha256"]
    assert result["estimated_cost_usd"] == 0.0



def _git_init(path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ade@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "ADE Tests"], cwd=path, check=True)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_git_branch_and_commit_are_approval_bound_and_never_force_push(tmp_path) -> None:
    _git_init(tmp_path)
    branch_plan = git_change_plan(tmp_path, "branch", branch="feature/verified-edit")
    assert branch_plan["force_push"] is False
    assert branch_plan["destructive_operations"] == "blocked_by_default"
    branch_result = git_change_apply(
        tmp_path,
        "branch",
        branch="feature/verified-edit",
        approval_fingerprint=branch_plan["approval_fingerprint"],
    )
    assert branch_result["status"] == "PASS"

    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")
    commit_plan = git_change_plan(
        tmp_path,
        "commit",
        message="test: verified change",
        paths=["README.md"],
        verification_command=[sys.executable, "-c", "print('verified')"],
    )
    stale = git_change_apply(
        tmp_path,
        "commit",
        message="test: verified change",
        paths=["README.md"],
        verification_command=[sys.executable, "-c", "print('verified')"],
        approval_fingerprint="wrong",
    )
    assert stale["status"] == "STALE_APPROVAL"
    committed = git_change_apply(
        tmp_path,
        "commit",
        message="test: verified change",
        paths=["README.md"],
        verification_command=[sys.executable, "-c", "print('verified')"],
        approval_fingerprint=commit_plan["approval_fingerprint"],
    )
    assert committed["status"] == "PASS"
    assert git_status(tmp_path)["status"] == "PASS"


class _EvidenceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        payload = json.dumps({"path": self.path, "result": "reservation revenue"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


def test_web_research_records_source_url_and_content_fingerprint() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EvidenceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = f"http://127.0.0.1:{server.server_port}"
        fetched = audited_web_fetch(f"{root}/evidence")
        assert fetched["status"] == "PASS"
        assert fetched["source"]["final_url"].startswith(root)
        assert fetched["content_sha256"]
        assert fetched["citation"]["content_sha256"] == fetched["content_sha256"]

        searched = audited_web_search("revpar decline", endpoint_template=f"{root}/search?q={{query}}")
        assert searched["status"] == "PASS"
        assert "revpar+decline" in searched["search_endpoint"]
        assert searched["evidence"]["citation"]["url"]
    finally:
        server.shutdown()
        server.server_close()


def test_provider_neutral_retrieval_has_local_backend_and_honest_cortex_boundary() -> None:
    local = retrieval_search(
        "reservation revenue",
        documents=[
            {"id": "a", "text": "reservation revenue by property"},
            {"id": "b", "text": "customer phone numbers"},
        ],
        backend="local",
    )
    assert local["status"] == "PASS"
    assert local["results"][0]["id"] == "a"

    cortex = retrieval_search("reservation revenue", backend="cortex_search")
    assert cortex["status"] == "SKIP_EXTERNAL"
    assert cortex["backend"] == "cortex_search"


def test_embedded_agent_sdk_preserves_toolregistry_and_per_tool_approval() -> None:
    from agentic_data_platform.models import Capability, Platform, Risk
    from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo_read",
            capability=Capability.DISCOVER,
            risk=Risk.READ_ONLY,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: {"status": "PASS", "value": args["value"]},
        )
    )
    registry.register(
        ToolDefinition(
            name="mutate_demo",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: {"status": "PASS"},
            requires_approval=True,
        )
    )

    session = EmbeddedAgentSession(registry)
    assert session.invoke("echo_read", {"value": 7})["value"] == 7
    waiting = session.invoke("mutate_demo", {})
    assert waiting["status"] == "AWAITING_APPROVAL"

    approved = EmbeddedAgentSession(registry, approval_callback=lambda envelope: envelope["tool"] == "mutate_demo")
    assert approved.invoke("mutate_demo", {})["status"] == "PASS"
    contract = sdk_contract()
    assert contract["approval_callbacks"] == "per-tool"
    assert contract["policy"] == "ToolRegistry inherited"


def test_account_admin_plan_inherits_exact_snowflake_governance() -> None:
    result = account_admin_plan(
        "ALTER WAREHOUSE ANALYTICS_WH SET WAREHOUSE_SIZE = 'LARGE'",
        environment="dev",
    )
    assert result["status"] == "PASS"
    assert result["administration"] is True
    assert result["independent_verification_required"] is True
    assert result["approval_fingerprint"]
    assert result["verification_plan"]


def test_gpu_job_planning_has_cost_guardrail_and_portable_local_execution(tmp_path) -> None:
    blocked = gpu_job_plan(
        backend="snowflake",
        image="example/model:1",
        command=["python", "train.py"],
        gpu_count=4,
        max_runtime_seconds=7200,
        hourly_cost_usd=10,
        max_cost_usd=5,
    )
    assert blocked["status"] == "BLOCKED_COST"

    plan = gpu_job_plan(
        backend="local_cuda",
        image="local/test",
        command=[sys.executable, "-c", "print('gpu-plan-ok')"],
        max_runtime_seconds=10,
        hourly_cost_usd=0,
        max_cost_usd=1,
    )
    assert plan["status"] == "PASS"
    run = gpu_job_run(tmp_path, plan, approval_fingerprint=plan["approval_fingerprint"])
    assert run["status"] == "PASS"
    assert "gpu-plan-ok" in run["stdout"]



def test_registered_advanced_tools_inherit_plan_and_approval_boundary(tmp_path) -> None:
    from agentic_data_platform.models import ActorMode, Environment, Risk, ToolRequest
    from agentic_data_platform.tools.builtin import build_tool_registry
    from agentic_data_platform.tools.registry import ToolInvocation

    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    expected = {
        "mode_contract",
        "model_route",
        "immutable_plan",
        "workspace_edit_plan",
        "workspace_edit_apply",
        "workspace_region_edit_plan",
        "workspace_region_edit_apply",
        "shell_plan",
        "shell_run",
        "git_change_plan",
        "git_change_apply",
        "web_fetch_audited",
        "web_search_audited",
        "retrieval_search",
        "context_select",
        "custom_agent_validate",
        "warehouse_object_search",
        "sql_playground",
        "chart_build",
        "forecast_series",
        "anomaly_compare",
        "document_extract",
        "document_snowflake_extract_plan",
        "document_snowflake_parse_plan",
        "document_compare",
        "embedded_agent_sdk_contract",
        "account_admin_plan",
        "gpu_job_plan",
        "gpu_job_run",
    }
    assert expected <= names

    request = ToolRequest(
        tool="workspace_edit_apply",
        operation="workspace_edit_apply",
        environment=Environment.DEV,
        risk=Risk.MUTATING,
        args={
            "workspace": str(tmp_path),
            "path": "blocked.txt",
            "content": "cannot run from plan mode",
            "approval_fingerprint": "irrelevant",
        },
    )
    with pytest.raises(PermissionError, match="plan mode cannot invoke"):
        registry.invoke(
            ToolInvocation(
                request=request,
                run_id="plan-boundary",
                approved=True,
                actor_mode=ActorMode.PLAN,
            )
        )


    with pytest.raises(PermissionError, match="ask mode cannot invoke"):
        registry.invoke(
            ToolInvocation(
                request=request,
                run_id="ask-boundary",
                approved=True,
                actor_mode=ActorMode.ASK,
            )
        )

    from agentic_data_platform.runtime.agent import AgentRuntime

    runtime = object.__new__(AgentRuntime)
    runtime.registry = registry
    ask_specs = runtime._tool_specs(ActorMode.ASK)
    assert ask_specs
    assert all(item["risk"] == "read_only" for item in ask_specs)
    assert "workspace_edit_apply" not in {item["name"] for item in ask_specs}
    assert "workspace_region_edit_apply" not in {item["name"] for item in ask_specs}



def test_agent_recovery_lifecycle_is_plan_approve_execute_verify_recertify(tmp_path) -> None:
    planned = agent_recovery_plan(tmp_path, scenario_id="watermark_defect")
    assert planned["status"] == "PASS"
    assert planned["phase"] == "AWAITING_APPROVAL"
    assert planned["external_mutation"] is False
    assert planned["approval_required"] is True
    assert planned["first_divergence"] == "source→raw"
    assert planned["root_cause"] == "WATERMARK_ADVANCED_BEYOND_EXTRACT"
    assert planned["evidence_count"] > 0
    assert planned["platform_coverage"]["snowflake"] is True
    assert planned["platform_coverage"]["airflow"] is True
    assert planned["platform_coverage"]["dbt"] is True
    assert planned["lifecycle"] == {
        "investigated": True,
        "planned": True,
        "approval_boundary": True,
        "executed": False,
        "verified": False,
        "recertified": False,
    }
    assert planned["coverage_fingerprint"]

    blocked = agent_recovery_execute(tmp_path, planned["incident_id"], approved=False)
    assert blocked["status"] == "AWAITING_APPROVAL"

    resolved = agent_recovery_execute(
        tmp_path,
        planned["incident_id"],
        approved=True,
        approved_by="capability-certification",
    )
    assert resolved["status"] == "PASS"
    assert resolved["state"] == "RESOLVED"
    assert resolved["external_mutation"] is False
    assert resolved["airflow_actions"][0]["operation"] == "bounded_backfill"
    assert resolved["dbt_selector"] == "stg_postgres_payment_transaction+"
    assert resolved["verification"]["status"] == "PASS"
    assert resolved["verification"]["affected_dbt_tests"] == "PASS"
    assert resolved["verification"]["pipeline_execution"] == "PASS"
    assert resolved["certification"] == "CERTIFIED"
    assert resolved["platform_coverage"]["snowflake"] is True
    assert resolved["platform_coverage"]["airflow"] is True
    assert resolved["platform_coverage"]["dbt"] is True
    assert resolved["lifecycle"]["executed"] is True
    assert resolved["lifecycle"]["verified"] is True
    assert resolved["lifecycle"]["recertified"] is True
    assert resolved["agent_mode_evidence_fingerprint"]


def test_web_workbench_exposes_same_governed_advanced_tools_as_registry(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from agentic_data_platform.api.app import create_app
    from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository

    repository = SQLiteControlPlaneRepository(tmp_path / "control-plane.db")
    client = TestClient(create_app(repository))

    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    advanced = domains.json()["advanced"]
    expected_operations = {
        "mode",
        "plan-create",
        "plan-verify",
        "edit-plan",
        "edit-apply",
        "shell-plan",
        "shell-run",
        "git-plan",
        "git-apply",
        "web-fetch",
        "web-search",
        "retrieval-search",
        "context-select",
        "agent-validate",
        "agent-recovery-plan",
        "agent-recovery-execute",
        "object-search",
        "sql-playground",
        "chart-build",
        "forecast",
        "anomaly",
        "document-extract",
        "sdk-contract",
        "account-admin-plan",
        "gpu-plan",
        "gpu-run",
    }
    assert expected_operations <= set(advanced)

    plan_mode = client.post(
        "/api/v1/advanced/mode",
        json={"args": {"mode": "plan"}, "actor_mode": "analyst", "environment": "dev"},
    )
    assert plan_mode.status_code == 200
    assert plan_mode.json()["mode"] == "plan"

    denied = client.post(
        "/api/v1/advanced/edit-apply",
        json={
            "args": {
                "workspace": str(tmp_path),
                "path": "should-not-exist.txt",
                "content": "blocked",
                "approval_fingerprint": "irrelevant",
            },
            "actor_mode": "plan",
            "environment": "dev",
            "approved": True,
        },
    )
    assert denied.status_code == 403
    assert not (tmp_path / "should-not-exist.txt").exists()



def test_code_mode_routes_to_lowest_cost_capable_model_under_budget() -> None:
    routed = route_model_for_mode(
        "code",
        [
            {"name": "premium-code", "capabilities": ["code"], "estimated_cost_usd": 0.18, "quality_score": 0.99},
            {"name": "economy-code", "capabilities": ["code"], "estimated_cost_usd": 0.03, "quality_score": 0.82},
            {"name": "cheap-no-code", "capabilities": ["chat"], "estimated_cost_usd": 0.001, "quality_score": 0.9},
        ],
        budget_usd=0.10,
    )
    assert routed["status"] == "PASS"
    assert routed["selected"]["name"] == "economy-code"
    assert routed["policy"] == "lowest_cost_capable_model"
    assert routed["routing_fingerprint"]


def test_snowflake_document_plans_use_current_ai_surfaces_and_are_read_only() -> None:
    extraction = snowflake_document_extract_plan(
        "@DB.SCHEMA.DOCS",
        "invoice.pdf",
        {"invoice_id": "Invoice number", "total": "Total amount"},
        scores=True,
    )
    assert extraction["status"] == "PASS"
    assert extraction["read_only"] is True
    assert "AI_EXTRACT(" in extraction["sql"]
    assert "TO_FILE('@DB.SCHEMA.DOCS', 'invoice.pdf')" in extraction["sql"]
    assert "scores => TRUE" in extraction["sql"]
    assert extraction["live"] == "NOT_RUN_EXTERNAL"

    parsed = snowflake_document_parse_plan(
        "@DB.SCHEMA.DOCS",
        "contract.docx",
        mode="LAYOUT",
        page_split=True,
    )
    assert parsed["status"] == "PASS"
    assert "AI_PARSE_DOCUMENT(" in parsed["sql"]
    assert "'page_split', TRUE" in parsed["sql"]
    assert parsed["read_only"] is True


def test_document_comparison_records_accuracy_agreement_and_cost() -> None:
    result = compare_document_extractions(
        {
            "fields": {"invoice_id": "INV-42", "total": "123.45"},
            "estimated_cost_usd": 0.0,
        },
        {
            "response": {"invoice_id": "INV-42", "total": "123.45"},
        },
        expected_fields={"invoice_id": "INV-42", "total": "123.45"},
        provider_cost_usd=0.004,
    )
    assert result["status"] == "PASS"
    assert result["agreement_rate"] == 1.0
    assert result["local_accuracy"] == 1.0
    assert result["provider_accuracy"] == 1.0
    assert result["cost"] == {"local_usd": 0.0, "provider_usd": 0.004}
    assert result["evaluation_fingerprint"]



def test_gpu_job_plans_materialize_snowflake_and_kubernetes_gpu_contracts(tmp_path) -> None:
    snowflake = gpu_job_plan(
        backend="snowflake",
        image="/DB.SCHEMA.REPO/train:1",
        command=["python", "train.py"],
        gpu_count=2,
        replicas=2,
        max_runtime_seconds=1800,
        hourly_cost_usd=1.0,
        max_cost_usd=10.0,
        compute_pool="SYSTEM_COMPUTE_POOL_GPU",
        job_name="ade_training_job",
    )
    assert snowflake["status"] == "PASS"
    assert snowflake["service_spec"]["spec"]["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == 2
    assert snowflake["execution_contract"]["cli"][:4] == ["snow", "spcs", "service", "execute-job"]
    assert snowflake["estimated_max_cost_usd"] == 2.0

    kubernetes = gpu_job_plan(
        backend="kubernetes",
        image="example/train:1",
        command=["python", "train.py"],
        gpu_count=1,
        replicas=3,
        namespace="ade",
        max_runtime_seconds=600,
        max_cost_usd=10.0,
    )
    assert kubernetes["status"] == "PASS"
    manifest = kubernetes["job_manifest"]
    assert manifest["spec"]["parallelism"] == 3
    assert manifest["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["nvidia.com/gpu"] == 1

    # External runners fail closed when their CLI/configuration is unavailable;
    # they never manufacture a live PASS from a materialized plan.
    external = gpu_job_run(
        tmp_path,
        snowflake,
        approval_fingerprint=snowflake["approval_fingerprint"],
    )
    assert external["status"] == "BLOCKED_EXTERNAL"
    assert external["artifact"]
