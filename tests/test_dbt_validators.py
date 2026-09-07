from __future__ import annotations

import json
import time

from agentic_data_platform.dbt.validators import (
    run_validators,
    validate_build_green,
    validate_deliverable_names,
    validate_dialect,
    validate_incremental_config,
    validate_nothing_built,
    validate_schema,
    validate_tests_pass,
)


def manifest_fixture():
    return {
        "nodes": {
            "model.demo.fact_orders": {
                "unique_id": "model.demo.fact_orders",
                "name": "fact_orders",
                "alias": "fact_orders",
                "resource_type": "model",
                "compiled_code": "SELECT order_id, amount FROM raw.orders",
                "config": {"materialized": "incremental", "unique_key": "order_id", "incremental_strategy": "merge"},
                "columns": {
                    "order_id": {"data_type": "INTEGER"},
                    "amount": {"data_type": "NUMBER"},
                },
            }
        },
        "sources": {},
    }


def test_all_pinned_validator_categories_have_deterministic_results(tmp_path):
    root = tmp_path / "project"
    (root / "target").mkdir(parents=True)
    manifest = manifest_fixture()
    catalog = {
        "nodes": {
            "model.demo.fact_orders": {
                "columns": {
                    "order_id": {"type": "INTEGER"},
                    "amount": {"type": "NUMBER"},
                }
            }
        }
    }
    run_results = {
        "args": {"which": "build"},
        "results": [
            {"unique_id": "model.demo.fact_orders", "status": "success"},
            {"unique_id": "test.demo.not_null_fact_orders_order_id", "status": "pass"},
        ],
    }
    (root / "target" / "manifest.json").write_text(json.dumps(manifest))
    (root / "target" / "catalog.json").write_text(json.dumps(catalog))
    (root / "target" / "run_results.json").write_text(json.dumps(run_results))

    results = run_validators(root, manifest=manifest, catalog=catalog, run_results=run_results, dialect="snowflake")
    names = {item["name"] for item in results["validators"]}
    assert names == {
        "dbt-build-green",
        "dbt-deliverable-names",
        "dbt-dialect-guard",
        "dbt-incremental-config",
        "dbt-nothing-built",
        "dbt-schema-verify",
        "dbt-tests-pass",
    }
    assert results["status"] == "PASS"


def test_build_green_rejects_nonexecuting_artifact(tmp_path):
    root = tmp_path / "project"
    (root / "target").mkdir(parents=True)
    (root / "target" / "run_results.json").write_text(
        json.dumps({"args": {"which": "compile"}, "results": [{"unique_id": "model.demo.x", "status": "success"}]})
    )
    result = validate_build_green(root, touched_models=["models/x.sql"], session_start_epoch=time.time() - 60)
    assert result.ok is False
    assert result.verdict == "non-executing-artifact"


def test_deliverable_incremental_dialect_schema_and_tests_fail_closed(tmp_path):
    manifest = manifest_fixture()
    bad_names = json.loads(json.dumps(manifest))
    bad_names["nodes"]["model.demo.fact_orders"]["name"] = "Fact Orders"
    assert validate_deliverable_names(bad_names).ok is False

    unsafe = json.loads(json.dumps(manifest))
    unsafe["nodes"]["model.demo.fact_orders"]["config"]["unique_key"] = None
    assert validate_incremental_config(unsafe).ok is False

    bad_sql = json.loads(json.dumps(manifest))
    bad_sql["nodes"]["model.demo.fact_orders"]["compiled_code"] = "SELECT FROM"
    assert validate_dialect(bad_sql, dialect="snowflake").ok is False

    catalog = {"nodes": {"model.demo.fact_orders": {"columns": {"order_id": {"type": "VARCHAR"}}}}}
    assert validate_schema(manifest, catalog).ok is False

    results = {"results": [{"unique_id": "test.demo.unique_fact_orders", "status": "fail", "message": "1 duplicate"}]}
    assert validate_tests_pass(results).ok is False

    root = tmp_path / "nothing"
    root.mkdir()
    assert validate_nothing_built(root, task_requires_build=True).ok is False
