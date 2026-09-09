from __future__ import annotations

import sqlite3
import sys

import pytest

from agentic_data_platform.advanced_capabilities import (
    anomaly_compare,
    apply_file_edit,
    build_chart_spec,
    command_plan,
    document_extract,
    forecast_series,
    immutable_plan,
    list_agent_definitions,
    mode_contract,
    plan_file_edit,
    run_command,
    save_agent_definition,
    search_warehouse_objects,
    select_context,
    sql_playground,
    verify_immutable_plan,
)


def test_mode_contracts_enforce_read_only_plan_and_code_data_boundary() -> None:
    plan = mode_contract("plan")
    code = mode_contract("code", budget_usd=0.25)
    edit = mode_contract("edit")

    assert plan["workspace_mutations"] is False
    assert plan["data_mutations"] is False
    assert code["data_mutations"] is False
    assert code["model_policy"] == "lowest_cost_capable_model"
    assert edit["workspace_mutations"] == "hash_bound_approval"
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


def test_file_edit_rejects_workspace_escape(tmp_path) -> None:
    with pytest.raises(ValueError):
        plan_file_edit(tmp_path, "../escape.txt", "nope")


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
    assert 6 in result["consensus"]


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
