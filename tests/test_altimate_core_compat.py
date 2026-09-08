from __future__ import annotations

from agentic_data_platform.sql.core_compat import (
    complete_sql,
    correct_sql,
    full_check,
    grade_sql,
    import_ddl,
    introspection_sql,
    optimize_schema_context,
    policy_check,
    prune_schema,
    resolve_term,
    semantic_equivalence,
    semantics,
    validate_sql,
)
from agentic_data_platform.tools.builtin import build_tool_registry


SCHEMA = {
    "orders": {
        "order_id": "INTEGER",
        "customer_id": "INTEGER",
        "amount": "NUMBER",
    },
    "customers": {
        "customer_id": "INTEGER",
        "email": "VARCHAR",
    },
}


def test_core_completion_validation_equivalence_and_grade():
    completion = complete_sql(
        "SELECT ord",
        len("SELECT ord"),
        schema_context=SCHEMA,
    )
    assert completion["success"] is True
    assert completion["suggestion_count"] >= 1

    valid = validate_sql(
        "SELECT order_id, amount FROM orders",
        schema_context=SCHEMA,
    )
    assert valid["valid"] is True

    invalid = validate_sql(
        "SELECT o.missing FROM orders o",
        schema_context=SCHEMA,
    )
    assert invalid["valid"] is False
    assert invalid["errors"][0]["rule"] == "missing_column"

    equivalent = semantic_equivalence(
        "SELECT order_id FROM orders",
        "select order_id from orders",
        schema_context=SCHEMA,
    )
    assert equivalent["success"] is True
    assert equivalent["equivalent"] is True

    grade = grade_sql(
        "SELECT order_id, amount FROM orders",
        schema_context=SCHEMA,
    )
    assert grade["grade"] in {"A", "B", "C", "D", "F"}
    assert 0 <= grade["score"] <= 100


def test_core_schema_context_pruning_and_term_resolution():
    levels = optimize_schema_context(schema_context=SCHEMA)
    assert len(levels["levels"]) == 5
    assert levels["levels"][0]["schema"]["tables"] == ["customers", "orders"]

    pruned = prune_schema(
        "SELECT order_id FROM orders",
        schema_context=SCHEMA,
    )
    assert pruned["relevant_tables"] == ["orders"]
    assert pruned["tables_pruned"] == 1

    resolved = resolve_term("customer email", schema_context=SCHEMA)
    assert resolved["match_count"] >= 1
    assert any(item["column"] == "email" for item in resolved["matches"])


def test_core_policy_semantics_check_and_correction():
    denied = policy_check(
        "SELECT * FROM customers",
        {
            "forbidden_tables": ["customers"],
            "warn_on_select_star": True,
        },
        schema_context=SCHEMA,
    )
    assert denied["allowed"] is False
    assert denied["violations"][0]["rule"] == "forbidden_table"

    semantic = semantics(
        "SELECT o.order_id FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
        schema_context=SCHEMA,
    )
    assert semantic["status"] == "PASS"
    assert semantic["has_schema"] is True

    checked = full_check(
        "SELECT email FROM customers",
        schema_context=SCHEMA,
    )
    assert checked["validation"]["valid"] is True
    assert checked["pii"]["accesses_pii"] is True

    corrected = correct_sql(
        "SELECT amount / 0 AS ratio FROM orders",
        schema_context=SCHEMA,
    )
    assert corrected["status"] == "PASS"
    assert corrected["corrected_sql"]
    assert "NULLIF" in corrected["corrected_sql"].upper()


def test_core_ddl_import_and_introspection_generation():
    result = import_ddl(
        "CREATE TABLE orders (order_id INTEGER NOT NULL, amount DECIMAL(18,2));",
        dialect="postgres",
    )
    assert result["success"] is True
    assert "orders" in result["schema"]
    assert result["schema"]["orders"]["columns"]["order_id"]["nullable"] is False

    snowflake = introspection_sql("snowflake", "HOTEL", schema_name="MART")
    assert snowflake["success"] is True
    assert "information_schema.columns" in snowflake["queries"]["columns"].casefold()

    bigquery = introspection_sql("bigquery", "hotel-project")
    assert bigquery["success"] is True
    assert "INFORMATION_SCHEMA.COLUMNS" in bigquery["queries"]["columns"]


def test_tool_registry_exposes_core_compatibility_surface():
    names = {item.name for item in build_tool_registry().definitions()}
    expected = {
        "altimate_core_complete",
        "altimate_core_equivalence",
        "altimate_core_grade",
        "altimate_core_optimize_context",
        "altimate_core_policy",
        "altimate_core_prune_schema",
        "altimate_core_resolve_term",
        "altimate_core_semantics",
        "altimate_core_validate",
        "altimate_core_check",
        "altimate_core_correct",
        "altimate_core_import_ddl",
        "altimate_core_introspection_sql",
        "altimate_core_fingerprint",
        "altimate_core_fix",
        "altimate_core_rewrite",
        "altimate_core_column_lineage",
        "altimate_core_schema_diff",
    }
    assert expected.issubset(names)
