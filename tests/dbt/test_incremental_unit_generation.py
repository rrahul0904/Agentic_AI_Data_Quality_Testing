from agentic_data_platform.dbt.generation import generate_unit_tests


def _manifest():
    return {
        "metadata": {"dbt_version": "1.12.3"},
        "nodes": {
            "model.analytics.fct_orders": {
                "unique_id": "model.analytics.fct_orders",
                "name": "fct_orders",
                "resource_type": "model",
                "raw_code": "{{ config(materialized='incremental', unique_key='id', incremental_strategy='merge') }}\nselect * from {{ ref('stg_orders') }} where {% if is_incremental() %} updated_at >= current_date - 2 {% endif %}",
                "compiled_code": "select id, amount, updated_at from analytics.stg_orders",
                "config": {
                    "materialized": "incremental",
                    "unique_key": "id",
                    "incremental_strategy": "merge",
                    "incremental_predicates": ["DBT_INTERNAL_DEST.updated_at > dateadd(day, -7, current_date)"],
                    "on_schema_change": "sync_all_columns",
                },
                "depends_on": {"nodes": ["model.analytics.stg_orders"]},
                "columns": {
                    "id": {"data_type": "NUMBER"},
                    "amount": {"data_type": "NUMBER"},
                    "updated_at": {"data_type": "TIMESTAMP"},
                },
            },
            "model.analytics.stg_orders": {
                "unique_id": "model.analytics.stg_orders",
                "name": "stg_orders",
                "resource_type": "model",
                "relation_name": "ANALYTICS.STG_ORDERS",
                "depends_on": {"nodes": []},
                "columns": {
                    "id": {"data_type": "NUMBER"},
                    "amount": {"data_type": "NUMBER"},
                    "updated_at": {"data_type": "TIMESTAMP"},
                },
            },
        },
        "sources": {},
    }


def test_incremental_unit_generation_detects_materialization_contract():
    result = generate_unit_tests(_manifest(), "fct_orders", max_scenarios=20)
    analysis = result["incremental_analysis"]
    assert analysis["is_incremental"] is True
    assert analysis["uses_is_incremental_macro"] is True
    assert analysis["unique_key"] == ["id"]
    assert analysis["incremental_strategy"] == "merge"
    assert analysis["merge"] is True
    assert "updated_records" in result["incremental_scenarios"]
    assert "late_arriving_records" in result["incremental_scenarios"]
    assert "duplicate_unique_keys" in result["incremental_scenarios"]
    assert "null_unique_keys" in result["incremental_scenarios"]
    assert "incremental_cutoff_boundary" in result["incremental_scenarios"]
    assert "outside_incremental_predicate" in result["incremental_scenarios"]
    assert "schema_change" in result["incremental_scenarios"]
    assert "is_incremental: true" in result["yaml"]
    assert "input: this" in result["yaml"]


def test_incremental_unit_generation_rejects_unsupported_dbt_version():
    manifest = _manifest()
    manifest["metadata"]["dbt_version"] = "1.7.9"
    try:
        generate_unit_tests(manifest, "fct_orders")
    except ValueError as exc:
        assert "dbt >= 1.8" in str(exc)
    else:
        raise AssertionError("expected unsupported dbt version to fail")
