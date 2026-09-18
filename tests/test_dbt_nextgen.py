import asyncio
from pathlib import Path

import yaml
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from agentic_data_platform.dbt.nextgen import (
    agents_schema,
    chart_compile,
    chart_validate,
    context_bundle,
    context_search,
    engine_readiness,
    explore_plan,
    explore_query_contract,
    lake_compute_plan,
    model_compute_plan,
    state_execution_contract,
    state_execute,
    state_plan,
    wizard_plan,
)
from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.dbt.mcp_server import mcp
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


def test_state_execution_contract_is_deterministic_and_guarded(tmp_path: Path):
    plan = {
        "fingerprint": "plan-123",
        "selectors": {
            "build": ["fact_orders"],
            "clone": ["dim_customer"],
            "defer": ["stg_orders"],
            "skip": ["dim_date"],
        },
        "actions": [],
    }
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    args = {
        "plan": plan,
        "project_dir": str(tmp_path),
        "state_dir": str(state_dir),
        "executable": "dbt-definitely-missing",
    }
    first = state_execution_contract(args)
    second = state_execution_contract(args)
    assert first["status"] == "PLAN"
    assert first["fingerprint"] == second["fingerprint"]
    assert [item["phase"] for item in first["commands"]] == ["clone", "build"]
    build = first["commands"][1]["argv"]
    assert "--defer" in build
    assert "--state" in build
    assert first["skipped_selectors"] == ["dim_date"]

    dry = state_execute({**args, "dry_run": True})
    assert dry["status"] == "DRY_RUN"
    assert dry["executed"] is False

    with pytest.raises(ValueError, match="approved_fingerprint"):
        state_execute({**args, "dry_run": False, "approved_fingerprint": "stale"})

    unavailable = state_execute({
        **args,
        "dry_run": False,
        "approved_fingerprint": first["fingerprint"],
    })
    assert unavailable["status"] == "SKIP_EXTERNAL"
    assert unavailable["executed"] is False


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



def test_explore_contract_and_execute_use_only_verified_sql(tmp_path: Path):
    semantic_yaml = tmp_path / "semantic-exec.yml"
    semantic_yaml.write_text(yaml.safe_dump({
        "name": "revenue_exec",
        "tables": [{
            "name": "orders",
            "dimensions": [{"name": "region", "description": "sales region"}],
            "metrics": [{"name": "revenue", "description": "premium revenue"}],
        }],
        "verified_queries": [
            {
                "name": "revenue_by_region",
                "question": "What is revenue by region?",
                "sql": "select 'east' as region, 42 as revenue",
                "verified_by": "analytics-governance",
            },
            {
                "name": "unsafe_revenue_delete",
                "question": "Delete revenue by region",
                "sql": "delete from orders",
                "verified_by": "bad-fixture",
            },
        ],
    }))
    db = tmp_path / "semantic-exec.db"
    SemanticRegistry(db).ingest_yaml(semantic_yaml)

    contract = explore_query_contract({
        "semantic_database": str(db),
        "question": "What is revenue by region?",
    })
    assert contract["status"] == "READY"
    assert contract["verified_query"]["name"] == "revenue_by_region"
    assert contract["sql"] == "select 'east' as region, 42 as revenue"
    assert contract["fingerprint"]

    no_match = explore_query_contract({
        "semantic_database": str(db),
        "question": "What is churn by cohort?",
    })
    assert no_match["status"] == "NEEDS_VERIFIED_QUERY"
    assert no_match["sql"] is None

    blocked = explore_query_contract({
        "semantic_database": str(db),
        "question": "Delete revenue by region",
        "verified_query_name": "unsafe_revenue_delete",
    })
    assert blocked["status"] == "BLOCKED"
    assert blocked["sql"] is None

    client = TestClient(create_app())
    response = client.post("/api/v1/dbt-next/explore-execute", json={
        "args": {
            "semantic_database": str(db),
            "question": "What is revenue by region?",
            "platform": "duckdb",
            "database": ":memory:",
            "row_limit": 10,
        }
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PASS"
    assert payload["contract"]["verified_query"]["name"] == "revenue_by_region"
    assert payload["execution"]["row_count"] == 1
    assert payload["execution"]["columns"] == ["region", "revenue"]



def test_lake_compute_plan_and_agent_schema():
    plan = lake_compute_plan({"source": "/tmp/orders.parquet", "source_type": "parquet", "limit": 25})
    assert plan["engine"] == "duckdb"
    assert "read_parquet" in plan["sql"]
    schema = agents_schema({})
    assert schema["status"] == "PASS"
    assert any(item["name"] == "semantic_explore" for item in schema["resources"])


def test_model_compute_plan_preserves_cross_engine_boundary():
    manifest = _manifest()
    result = model_compute_plan({
        "manifest": manifest,
        "model_engines": {"a": "lake", "b": "warehouse"},
    })
    assert result["status"] == "PASS"
    assert result["counts"]["lake"] == 1
    assert result["counts"]["warehouse"] == 1
    assert result["counts"]["cross_engine_boundaries"] == 1
    boundary = result["cross_engine_boundaries"][0]
    assert boundary["upstream"] == "model.demo.a"
    assert boundary["downstream"] == "model.demo.b"
    assert boundary["contract"] == "materialized-relation-boundary"


def test_context_accepts_adapter_fed_unstructured_records():
    bundle = context_bundle({
        "manifest": _manifest(),
        "records": [{
            "id": "jira-123",
            "source": "jira",
            "type": "ticket",
            "text": "Revenue metric changed because premium bookings now exclude refunds.",
            "metadata": {"project": "finance"},
        }],
    })
    assert bundle["counts"]["records"] == 1
    hits = context_search({"bundle": bundle["bundle"], "query": "premium refunds"})
    assert hits["count"] == 1
    assert hits["results"][0]["source"] == "record:jira"
    assert hits["results"][0]["record_id"] == "jira-123"


def test_api_and_cli_publish_complete_dbt_next_domain():
    expected = {
        "engine-readiness", "state-plan", "state-contract", "state-execute", "context-bundle", "context-search",
        "wizard-plan", "explore-plan", "explore-contract", "explore-execute", "chart-validate", "chart-compile",
        "model-compute-plan", "lake-plan", "lake-run", "agents-schema",
    }
    assert expected.issubset(DOMAIN_CLI_TOOLS["dbt-next"])
    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert expected.issubset(domains.json()["dbt-next"])
    schema = client.post("/api/v1/dbt-next/agents-schema", json={"args": {}})
    assert schema.status_code == 200
    assert schema.json()["schema_version"] == "ade-agents/1.0"


def test_mcp_server_discovers_dbt_context_tools_and_resource():
    async def probe():
        async with Client(mcp) as client:
            tool_page = await client.list_tools()
            tool_names = {tool.name for tool in tool_page.tools}
            assert {
                "dbt_context_search", "dbt_context_bundle", "dbt_wizard_plan",
                "dbt_explore_plan", "dbt_explore_query_contract", "dbt_state_plan", "dbt_state_execution_contract", "dbt_chart_compile",
                "dbt_model_compute_plan", "dbt_lake_compute_plan",
            }.issubset(tool_names)
            resource_page = await client.list_resources()
            uris = {str(resource.uri) for resource in resource_page.resources}
            assert "ade://dbt/agents-schema" in uris

    asyncio.run(probe())


def test_engine_readiness_override_and_registry_surface():
    readiness = engine_readiness({"version_output": "dbt 2.0.0 fusion"})
    assert readiness["status"] == "PASS"
    assert readiness["engine_family"] == "dbt-v2-or-fusion"
    registry = build_tool_registry()
    for name in (
        "dbt_next_state_plan", "dbt_next_state_execution_contract", "dbt_next_state_execute",
        "dbt_next_wizard_plan", "dbt_next_explore_plan", "dbt_next_explore_query_contract", "dbt_next_explore_execute",
        "dbt_next_chart_compile", "dbt_next_model_compute_plan", "dbt_next_lake_compute_plan",
        "dbt_next_context_bundle", "dbt_next_agents_schema",
    ):
        assert registry.describe(name).name == name
