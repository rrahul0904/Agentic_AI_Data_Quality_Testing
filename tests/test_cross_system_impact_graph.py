from __future__ import annotations

from pathlib import Path

from agentic_data_platform.platform.graph import PlatformAssetGraph


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "hospitality-snowflake-data-platform"


def test_platform_graph_contains_cross_airflow_task_dependencies():
    graph = PlatformAssetGraph.build(PROJECT).snapshot()
    edge_types = graph["edge_types"]
    assert edge_types.get("contains", 0) > 0
    assert edge_types.get("executes_before", 0) > 0


def test_platform_graph_attaches_dashboard_consumers_when_references_exist():
    graph = PlatformAssetGraph.build(PROJECT).snapshot()
    consumers = [node for node in graph["nodes"] if node["kind"] == "consumer"]
    assert any(node["name"].startswith("dashboard:") for node in consumers)
    assert graph["edge_types"].get("consumed_by", 0) > 0


def test_impact_response_has_business_consumer_categories():
    platform = PlatformAssetGraph.build(PROJECT)
    snapshot = platform.snapshot()
    candidates = [
        node["name"] for node in snapshot["nodes"]
        if node["kind"] in {"dbt_model", "mart"} and node["name"].startswith("fact_")
    ]
    assert candidates
    result = platform.impact(candidates[0], depth=12)
    assert "affected_metrics" in result
    assert "affected_consumers" in result
    assert "affected_marts" in result
