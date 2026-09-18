from pathlib import Path

import yaml

from agentic_data_platform.dbt.nextgen import (
    agents_schema,
    chart_compile,
    chart_validate,
    context_bundle,
    context_search,
    engine_readiness,
    explore_plan,
    lake_compute_plan,
    state_plan,
    wizard_plan,
)
from agentic_data_platform.semantic.registry import SemanticRegistry
from agentic_data_platform.tools.builtin import build_tool_registry


def _manifest(raw_a="select 1", raw_b="select * from {{ ref('a') }}"):
    return {
        "nodes": {
            "model.demo.a": {
                "unique_id": "model.demo.a", "name": "a", "resource_type": "model",
                "raw_code": raw_a, "config": {"materialized": "table"}, "depends_on": {"nodes": []},
            },
            "model.demo.b": {
                "unique_id": "model.demo.b", "name": "b", "resource_type": "model",
                "raw_code": raw_b, "config": {"materialized": "table"}, "depends_on": {"nodes": ["model.demo.a"]},
            },
        },
        "child_map": {"model.demo.a": ["model.demo.b"], "model.demo.b": []},
        "parent_map": {"model.demo.a": [], "model.demo.b": ["model.demo.a"]},
    }


def test_state_plan_builds_changed_and_downstream():
    previous = _manifest("select 1")
    current = _manifest("select 2")
    result = state_plan({"manifest": current, "previous_manifest": previous})
    assert result["status"] == "PASS"
    assert result["counts"]["build"] == 2
    assert {item["node"] for item in result["actions"] if item["action"] == "BUILD"} == {
        "model.demo.a", "model.demo.b"
    }


def test_state_plan_can_classify_clone_defer_and_skip():
    manifest = _manifest()
    result = state_plan({
        "manifest": manifest,
        "previous_manifest": manifest,
        "clone_available": ["model.demo.a"],
        "defer_available": ["model.demo.b"],
    })
    by_node = {item["node"]: item["action"] for item in result["actions"]}
    assert by_node == {"model.demo.a": "CLONE", "model.demo.b": "DEFER"}


def test_chart_yaml_is_versionable_and_read_only():
    spec = {
        "dashboard": {
            "name": "executive_revenue",
            "description": "Revenue KPIs",
            "charts": [{"name": "revenue_by_month", "type": "line", "metric": "revenue", "dimension": "month"}],
        }
    }
    validated = chart_validate({"spec": spec})
    assert validated["status"] == "PASS"
    compiled = chart_compile({"spec": spec})
    assert compiled["status"] == "PASS"
    assert "power-bi-contract" in compiled["compiled"]["targets"]

    blocked = chart_validate({"spec": {"dashboard": {"name": "bad", "charts": [{"name": "x", "sql": "delete from t"}]}}})
    assert blocked["status"] == "FAIL"


def test_context_and_wizard_use_manifest_evidence():
    manifest = _manifest()
    bundle = context_bundle({"manifest": manifest})
    assert bundle["counts"]["models"] == 2
    hits = context_search({"bundle": bundle["bundle"], "query": "model b"})
    assert hits["count"] >= 1
    plan = wizard_plan({"bundle": bundle["bundle"], "question": "show downstream impact for model a"})
    assert "lineage-impact" in plan["intents"]
    assert "dbt_impact" in plan["recommended_tools"]


def test_semantic_explore_is_grounded(tmp_path: Path):
    semantic_yaml = tmp_path / "semantic.yml"
    semantic_yaml.write_text(yaml.safe_dump({
        "name": "revenue_model",
        "tables": [{
            "name": "orders",
            "dimensions": [{"name": "region", "description": "sales region"}],
            "time_dimensions": [{"name": "order_month", "description": "order month"}],
            "metrics": [{"name": "revenue", "description": "premium revenue"}],
        }],
        "verified_queries": [{
            "name": "revenue_by_region",
            "question": "What is revenue by region?",
            "sql": "select region, sum(revenue) revenue from orders group by region",
        }],
    }))
    db = tmp_path / "semantic.db"
    SemanticRegistry(db).ingest_yaml(semantic_yaml)
    result = explore_plan({"semantic_database": str(db), "question": "What is revenue by region?"})
    assert result["status"] == "READY"
    assert any(item["name"] == "revenue" for item in result["metrics"])
    assert result["verified_queries"]


def test_lake_compute_plan_and_agent_schema():
    plan = lake_compute_plan({"source": "/tmp/orders.parquet", "source_type": "parquet", "limit": 25})
    assert plan["engine"] == "duckdb"
    assert "read_parquet" in plan["sql"]
    schema = agents_schema({})
    assert schema["status"] == "PASS"
    assert any(item["name"] == "semantic_explore" for item in schema["resources"])


def test_engine_readiness_override_and_registry_surface():
    readiness = engine_readiness({"version_output": "dbt 2.0.0 fusion"})
    assert readiness["status"] == "PASS"
    assert readiness["engine_family"] == "dbt-v2-or-fusion"
    registry = build_tool_registry()
    for name in (
        "dbt_next_state_plan", "dbt_next_wizard_plan", "dbt_next_explore_plan",
        "dbt_next_chart_compile", "dbt_next_lake_compute_plan", "dbt_next_context_bundle",
        "dbt_next_agents_schema",
    ):
        assert registry.describe(name).name == name
