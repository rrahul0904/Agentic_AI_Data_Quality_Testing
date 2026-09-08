from __future__ import annotations

import yaml

from agentic_data_platform.dbt.generation import generate_schema_tests, generate_unit_tests


def manifest_fixture():
    return {
        "nodes": {
            "model.demo.fact_orders": {
                "unique_id": "model.demo.fact_orders",
                "name": "fact_orders",
                "resource_type": "model",
                "compiled_code": (
                    "SELECT o.order_id, CASE WHEN o.amount > 0 THEN o.amount / o.quantity ELSE 0 END AS unit_price, "
                    "SUM(o.amount) OVER (PARTITION BY o.guest_id) AS lifetime_amount "
                    "FROM raw.orders o JOIN raw.guests g ON o.guest_id = g.guest_id "
                    "WHERE o.status = 'CONFIRMED'"
                ),
                "config": {"materialized": "incremental"},
                "depends_on": {"nodes": ["source.demo.orders", "source.demo.guests"]},
                "columns": {
                    "order_id": {"data_type": "INTEGER", "description": "Primary key"},
                    "unit_price": {"data_type": "NUMBER"},
                    "lifetime_amount": {"data_type": "NUMBER"},
                },
            },
            "test.demo.not_null_fact_orders_order_id": {
                "unique_id": "test.demo.not_null_fact_orders_order_id",
                "resource_type": "test",
                "depends_on": {"nodes": ["model.demo.fact_orders"]},
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "order_id"}},
            },
        },
        "sources": {
            "source.demo.orders": {
                "unique_id": "source.demo.orders",
                "name": "orders",
                "source_name": "raw",
                "resource_type": "source",
                "relation_name": "raw.orders",
                "columns": {
                    "order_id": {"data_type": "INTEGER"},
                    "guest_id": {"data_type": "INTEGER"},
                    "amount": {"data_type": "NUMBER"},
                    "quantity": {"data_type": "INTEGER"},
                    "status": {"data_type": "VARCHAR"},
                },
            },
            "source.demo.guests": {
                "unique_id": "source.demo.guests",
                "name": "guests",
                "source_name": "raw",
                "resource_type": "source",
                "relation_name": "raw.guests",
                "columns": {
                    "guest_id": {"data_type": "INTEGER"},
                    "email": {"data_type": "VARCHAR"},
                },
            },
        },
    }


def test_schema_test_generator_preserves_existing_tests_and_proposes_missing():
    result = generate_schema_tests(
        manifest_fixture(),
        "fact_orders",
        relationships={"order_id": {"to": "ref('dim_order')", "field": "order_id"}},
    )
    assert result["applied"] is False
    assert "not_null" not in result["proposals"]["order_id"]
    assert "unique" in result["proposals"]["order_id"]
    parsed = yaml.safe_load(result["yaml"])
    assert parsed["version"] == 2
    assert parsed["models"][0]["name"] == "fact_orders"


def test_unit_test_generator_detects_logic_and_emits_dbt_yaml():
    result = generate_unit_tests(manifest_fixture(), "fact_orders", dialect="snowflake", max_scenarios=6)
    assert result["success"] is True
    assert result["applied"] is False
    assert {"case_when", "join", "window", "division", "filter"}.issubset(set(result["logic_categories"]))
    assert result["dependency_count"] == 2
    assert result["tests"]
    parsed = yaml.safe_load(result["yaml"])
    assert "unit_tests" in parsed
    assert parsed["unit_tests"][0]["model"] == "fact_orders"
    first_given = parsed["unit_tests"][0]["given"][0]
    assert "rows" in first_given
    assert isinstance(first_given["rows"][0]["order_id"], int)


def test_incremental_unit_test_generation_is_deterministic_and_merge_aware():
    manifest = manifest_fixture()
    model = manifest["nodes"]["model.demo.fact_orders"]
    model["config"] = {
        "materialized": "incremental",
        "unique_key": "order_id",
        "incremental_strategy": "merge",
        "incremental_predicates": ["DBT_INTERNAL_DEST.order_id >= 100"],
        "on_schema_change": "append_new_columns",
    }
    model["raw_code"] = (
        "{{ config(materialized='incremental', unique_key='order_id') }} "
        "select * from {{ source('raw', 'orders') }} "
        "{% if is_incremental() %} where order_id >= 100 {% endif %}"
    )

    first = generate_unit_tests(manifest, "fact_orders", dialect="snowflake", max_scenarios=14)
    second = generate_unit_tests(manifest, "fact_orders", dialect="snowflake", max_scenarios=14)

    assert first["yaml"] == second["yaml"]
    assert first["incremental_analysis"]["is_incremental"] is True
    assert first["incremental_analysis"]["uses_is_incremental_macro"] is True
    assert first["incremental_analysis"]["unique_key"] == ["order_id"]
    assert first["incremental_analysis"]["merge"] is True
    assert first["incremental_analysis"]["incremental_predicates"]
    assert {
        "new_records",
        "updated_records",
        "duplicate_unique_keys",
        "null_unique_keys",
        "incremental_cutoff_boundary",
        "outside_incremental_predicate",
        "schema_change",
    }.issubset(set(first["incremental_scenarios"]))
    parsed = yaml.safe_load(first["yaml"])
    names = [item["name"] for item in parsed["unit_tests"]]
    assert len(names) == len(set(names))
    incremental = [item for item in parsed["unit_tests"] if "_incremental_" in item["name"]]
    assert incremental
    assert all(item["overrides"]["macros"]["is_incremental"] is True for item in incremental)
