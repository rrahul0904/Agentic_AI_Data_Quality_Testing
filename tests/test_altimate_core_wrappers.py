from __future__ import annotations

import json

from agentic_data_platform.sql.core_wrappers import (
    classify_schema_pii,
    compare_sql,
    export_ddl,
    extract_sql_metadata,
    generate_sql_tests,
    migration_safety,
    parse_dbt_project,
    query_pii,
    track_lineage,
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


def test_pii_compare_ddl_and_metadata_wrappers():
    classified = classify_schema_pii(schema_context=SCHEMA)
    assert classified["success"] is True
    assert any(item["column"] == "email" for item in classified["findings"])

    exposure = query_pii(
        "SELECT email FROM customers",
        schema_context=SCHEMA,
    )
    assert exposure["success"] is True
    assert exposure["accesses_pii"] is True

    same = compare_sql(
        "SELECT order_id FROM orders",
        "select order_id from orders",
    )
    assert same["identical"] is True

    changed = compare_sql(
        "SELECT order_id FROM orders",
        "SELECT amount FROM orders",
    )
    assert changed["identical"] is False
    assert changed["diff_count"] >= 1

    ddl = export_ddl(schema_context=SCHEMA)
    assert ddl["table_count"] == 2
    assert "CREATE TABLE customers" in ddl["ddl"]

    metadata = extract_sql_metadata(
        "WITH x AS (SELECT order_id, amount FROM orders) SELECT SUM(amount) FROM x"
    )
    assert "orders" in metadata["tables"]
    assert "X" in {item.upper() for item in metadata["ctes"]}
    assert metadata["functions"]


def test_migration_safety_and_generated_sql_tests():
    migration = migration_safety(
        "CREATE TABLE orders(order_id INTEGER NOT NULL, amount DECIMAL(18,2));",
        "CREATE TABLE orders(order_id INTEGER NOT NULL);",
        dialect="postgres",
    )
    assert migration["success"] is True
    assert migration["safe"] is False
    assert any(item["operation"] == "drop_column" for item in migration["findings"])

    generated = generate_sql_tests(
        "SELECT amount / customer_id FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
        schema_context=SCHEMA,
    )
    categories = {item["category"] for item in generated["tests"]}
    assert {"syntax", "edge_case", "null", "boundary", "join", "schema"}.issubset(categories)


def test_parse_dbt_and_multi_query_lineage(tmp_path):
    project = tmp_path / "dbt"
    target = project / "target"
    target.mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        "name: demo\nversion: '1.0'\nprofile: demo\n"
    )
    manifest = {
        "nodes": {
            "model.demo.orders": {
                "unique_id": "model.demo.orders",
                "name": "orders",
                "resource_type": "model",
            },
            "test.demo.orders": {
                "unique_id": "test.demo.orders",
                "name": "orders_test",
                "resource_type": "test",
            },
            "seed.demo.raw": {
                "unique_id": "seed.demo.raw",
                "name": "raw",
                "resource_type": "seed",
            },
        },
        "sources": {
            "source.demo.raw": {
                "unique_id": "source.demo.raw",
                "name": "raw",
                "resource_type": "source",
            }
        },
    }
    (target / "manifest.json").write_text(json.dumps(manifest))

    parsed = parse_dbt_project(project)
    assert parsed["model_count"] == 1
    assert parsed["source_count"] == 1
    assert parsed["test_count"] == 1
    assert parsed["seed_count"] == 1

    lineage = track_lineage(
        [
            "SELECT order_id, amount FROM orders",
            "SELECT customer_id, email FROM customers",
        ],
        schema_context=SCHEMA,
    )
    assert lineage["success"] is True
    assert len(lineage["queries"]) == 2
    assert lineage["edge_count"] >= 4


def test_registry_has_all_reference_core_tool_ids():
    names = {item.name for item in build_tool_registry().definitions()}
    expected = {
        "altimate_core_check",
        "altimate_core_classify_pii",
        "altimate_core_column_lineage",
        "altimate_core_compare",
        "altimate_core_complete",
        "altimate_core_correct",
        "altimate_core_equivalence",
        "altimate_core_export_ddl",
        "altimate_core_extract_metadata",
        "altimate_core_fingerprint",
        "altimate_core_fix",
        "altimate_core_grade",
        "altimate_core_import_ddl",
        "altimate_core_introspection_sql",
        "altimate_core_migration",
        "altimate_core_optimize_context",
        "altimate_core_parse_dbt",
        "altimate_core_policy",
        "altimate_core_prune_schema",
        "altimate_core_query_pii",
        "altimate_core_resolve_term",
        "altimate_core_rewrite",
        "altimate_core_schema_diff",
        "altimate_core_semantics",
        "altimate_core_testgen",
        "altimate_core_track_lineage",
        "altimate_core_validate",
    }
    assert expected.issubset(names)
