from __future__ import annotations

import duckdb
import pytest

from agentic_data_platform.connectors.duckdb import DuckDBConnector
from agentic_data_platform.sql.parity import (
    analyze_sql,
    autocomplete_sql,
    classify_sql,
    diff_sql,
    execute_sql,
    explain_sql,
    fingerprint_sql,
    fix_sql,
    format_sql,
    optimize_sql,
    rewrite_sql,
    translate_sql,
)


def test_sql_classification_is_ast_based_and_fail_closed():
    assert classify_sql("WITH x AS (SELECT 1 AS id) SELECT * FROM x")["query_type"] == "read"
    assert classify_sql("UPDATE accounts SET active = 0")["query_type"] == "write"
    blocked = classify_sql("DROP SCHEMA analytics")
    assert blocked["query_type"] == "write"
    assert blocked["blocked"] is True


def test_sql_fingerprint_contains_only_structure():
    result = fingerprint_sql("SELECT SUM(amount) OVER (PARTITION BY guest_id) AS total FROM payments")
    assert result["table_count"] == 1
    assert result["function_count"] >= 1
    assert result["has_window_functions"] is True
    assert result["node_count"] > 4


def test_format_translate_and_ast_diff():
    formatted = format_sql("select id,amount from orders where amount>10", "snowflake")
    assert formatted["success"] is True
    assert "SELECT" in formatted["formatted_sql"]

    translated = translate_sql(
        "SELECT DATE_TRUNC(order_date, MONTH) AS month FROM orders",
        "bigquery",
        "snowflake",
    )
    assert translated["success"] is True
    assert translated["translated_sql"]

    same = diff_sql("select id from orders", "SELECT id FROM orders", "snowflake")
    assert same["has_changes"] is False
    changed = diff_sql("SELECT id FROM orders", "SELECT id, amount FROM orders", "snowflake")
    assert changed["has_changes"] is True
    assert changed["change_count"] >= 1


def test_sql_analyze_and_optimize_return_evidence():
    result = analyze_sql("SELECT * FROM a CROSS JOIN b", "snowflake")
    assert result["parseable"] is True
    assert result["classification"]["query_type"] == "read"
    assert any(item["rule_id"] in {"SELECT_STAR", "CARTESIAN_JOIN"} for item in result["findings"])
    assert all("confidence" in item and "location" in item for item in result["findings"])

    optimized = optimize_sql("SELECT * FROM orders WHERE 1 = 1", "snowflake")
    assert optimized["success"] is True
    assert optimized["confidence"] in {"high", "medium"}


def test_rewrite_expands_star_and_repairs_null_and_division():
    schema = {"orders": {"id": "INTEGER", "amount": "NUMBER", "cancelled_at": "TIMESTAMP"}}
    rewritten = rewrite_sql(
        "SELECT *, amount / 0 AS bad_ratio FROM orders WHERE cancelled_at = NULL",
        "snowflake",
        schema,
    )
    assert rewritten["success"] is True
    assert rewritten["rewrite_count"] >= 3
    sql = rewritten["rewritten_sql"].upper()
    assert "IS NULL" in sql
    assert "NULLIF" in sql
    assert "ID" in sql and "AMOUNT" in sql

    fixed = fix_sql("SELECT amount / quantity FROM orders WHERE deleted_at != NULL", "snowflake")
    assert fixed["success"] is True
    assert fixed["improved"] is True
    assert fixed["fixed_sql"]


def test_schema_aware_autocomplete_resolves_alias():
    schema = {"analytics.orders": {"order_id": "INTEGER", "order_total": "NUMBER", "guest_id": "INTEGER"}}
    result = autocomplete_sql("SELECT o.ord", "ord", schema)
    assert result["schema_aware"] is True

    alias = autocomplete_sql("SELECT o.ord FROM analytics.orders o", "", schema)
    labels = {item["label"] for item in alias["items"]}
    assert {"order_id", "order_total"}.issubset(labels)


def test_duckdb_execute_and_explain_are_read_only_and_bounded():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE orders AS SELECT range AS id FROM range(20)")
    connector = DuckDBConnector(connection)

    result = execute_sql(connector, "SELECT * FROM orders ORDER BY id", "duckdb", row_limit=5)
    assert result["status"] == "PASS"
    assert result["row_count"] == 5
    assert result["truncated"] is True

    plan = explain_sql(connector, "SELECT COUNT(*) FROM orders", "duckdb")
    assert plan["status"] == "PASS"
    assert plan["metadata"]["plan"]

    with pytest.raises(PermissionError):
        execute_sql(connector, "DELETE FROM orders", "duckdb")


def test_registry_exposes_full_sql_parity_surface():
    from agentic_data_platform.tools.builtin import build_tool_registry

    names = {item.name for item in build_tool_registry().definitions()}
    expected = {
        "sql_analyze", "sql_autocomplete", "sql_classify", "sql_diff", "sql_execute", "sql_explain",
        "sql_fix", "sql_format", "sql_optimize", "sql_rewrite", "sql_translate", "sql_fingerprint",
    }
    assert expected.issubset(names)
