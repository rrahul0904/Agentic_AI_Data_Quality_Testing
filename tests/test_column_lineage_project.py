from __future__ import annotations

import json

from agentic_data_platform.dbt.manifest_graph import DbtArtifacts
from agentic_data_platform.lineage.dbt import DbtColumnGraph
from agentic_data_platform.lineage.engine import analyze_column_lineage


def test_complex_sql_lineage_resolves_nested_cte_join_case_window():
    sql = """
    WITH orders AS (
      SELECT order_id, guest_id, amount FROM raw.orders
    ),
    enriched AS (
      SELECT o.order_id,
             COALESCE(o.amount, 0) AS amount,
             g.email,
             SUM(o.amount) OVER (PARTITION BY o.guest_id) AS guest_total
      FROM orders o
      JOIN raw.guests g ON o.guest_id = g.guest_id
    )
    SELECT order_id,
           CASE WHEN amount > 0 THEN amount ELSE 0 END AS positive_amount,
           email,
           guest_total
    FROM enriched
    """
    schema = {
        "raw.orders": {"order_id": "INTEGER", "guest_id": "INTEGER", "amount": "NUMBER"},
        "raw.guests": {"guest_id": "INTEGER", "email": "TEXT"},
    }
    result = analyze_column_lineage(sql, dialect="snowflake", schema=schema)
    assert result["parseable"] is True
    by_target = {item["target"]: item for item in result["mappings"]}
    assert any(item["column"] == "amount" for item in by_target["positive_amount"]["sources"]), result
    assert any(item["column"] == "amount" for item in by_target["guest_total"]["sources"])
    assert by_target["email"]["sources"] == [{"table": "raw.guests", "column": "email"}]


def test_ambiguous_unqualified_reference_is_never_guessed():
    result = analyze_column_lineage(
        "SELECT id FROM left_table l JOIN right_table r ON l.id = r.id",
        dialect="snowflake",
        schema={"left_table": {"id": "INTEGER"}, "right_table": {"id": "INTEGER"}},
    )
    assert result["status"] == "PARTIAL"
    assert any("id:" in item for item in result["ambiguous_references"])


def _fixture_artifacts() -> DbtArtifacts:
    nodes = {}
    parent_map = {}
    child_map = {}

    nodes["source.demo.raw_reservation"] = {
        "unique_id": "source.demo.raw_reservation",
        "name": "raw_reservation",
        "resource_type": "source",
        "relation_name": "DB.RAW.RAW_RESERVATION",
        "database": "DB",
        "schema": "RAW",
        "identifier": "raw_reservation",
        "columns": {"reservation_id": {"data_type": "INTEGER"}},
    }

    previous = "source.demo.raw_reservation"
    relation = "DB.RAW.RAW_RESERVATION"
    for name in [
        "stg_reservation",
        "int_reservation",
        "core_reservation",
        "fact_reservation",
        "mart_reservation",
    ]:
        node_id = f"model.demo.{name}"
        nodes[node_id] = {
            "unique_id": node_id,
            "name": name,
            "resource_type": "model",
            "relation_name": f"DB.ANALYTICS.{name.upper()}",
            "database": "DB",
            "schema": "ANALYTICS",
            "alias": name,
            "compiled_code": f"SELECT reservation_id FROM {relation}",
            "depends_on": {"nodes": [previous]},
            "columns": {"reservation_id": {"data_type": "INTEGER"}},
        }
        parent_map[node_id] = [previous]
        child_map.setdefault(previous, []).append(node_id)
        previous = node_id
        relation = f"DB.ANALYTICS.{name.upper()}"

    manifest = {
        "nodes": {key: value for key, value in nodes.items() if value["resource_type"] != "source"},
        "sources": {key: value for key, value in nodes.items() if value["resource_type"] == "source"},
        "parent_map": parent_map,
        "child_map": child_map,
    }
    catalog_nodes = {
        key: {"columns": {"reservation_id": {"name": "reservation_id", "type": "INTEGER"}}}
        for key, value in nodes.items()
        if value["resource_type"] != "source"
    }
    catalog_sources = {
        key: {"columns": {"reservation_id": {"name": "reservation_id", "type": "INTEGER"}}}
        for key, value in nodes.items()
        if value["resource_type"] == "source"
    }
    return DbtArtifacts(
        manifest=manifest,
        catalog={"nodes": catalog_nodes, "sources": catalog_sources},
    )


def test_dbt_column_graph_resolves_five_hop_project_lineage():
    graph = DbtColumnGraph(_fixture_artifacts())
    path = graph.path("raw_reservation", "reservation_id", "mart_reservation", "reservation_id")
    assert path["found"] is True
    assert path["hops"] == 5

    upstream = graph.upstream("mart_reservation", "reservation_id")
    assert upstream["upstream"][-1]["resource_type"] == "source"
    impact = graph.impact("raw_reservation", "reservation_id")
    assert impact["affected_count"] == 5
    assert impact["severity"] in {"MEDIUM", "HIGH"}


def test_dbt_column_graph_diff_detects_changed_expression():
    before = DbtColumnGraph(_fixture_artifacts())
    artifacts = _fixture_artifacts()
    artifacts.manifest["nodes"]["model.demo.fact_reservation"]["compiled_code"] = (
        "SELECT reservation_id + 0 AS reservation_id FROM DB.ANALYTICS.CORE_RESERVATION"
    )
    after = DbtColumnGraph(artifacts)
    diff = before.diff(after)
    assert diff["changed"] is True
    assert diff["added_edges"] or diff["removed_edges"]


def test_project_graph_is_serializable():
    graph = DbtColumnGraph(_fixture_artifacts())
    payload = graph.graph()
    assert json.loads(json.dumps(payload))["summary"]["edges"] == 5
    assert len(graph.fingerprint()) == 64


def test_physical_lineage_never_includes_cte_or_table_aliases():
    result = analyze_column_lineage("WITH x AS (SELECT a.id FROM actual a) SELECT id FROM x")
    assert result["mappings"][0]["sources"] == [{"table": "actual", "column": "id"}]


def test_constant_cte_is_resolved_without_inventing_a_source():
    result = analyze_column_lineage("WITH x AS (SELECT 1 AS id) SELECT id FROM x")
    assert result["status"] == "PASS"
    assert result["mappings"][0]["sources"] == []


def test_unresolved_terminal_is_not_promoted_to_a_source():
    result = analyze_column_lineage("SELECT mystery.id")
    assert result["status"] == "PARTIAL"
    assert result["mappings"][0]["sources"] == []
    assert result["unresolved_references"]
