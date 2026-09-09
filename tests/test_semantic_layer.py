from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.semantic import (
    CortexAnalystAdapter,
    SemanticRegistry,
    SnowflakeSemanticAdapter,
    build_analyst_request,
    evaluate_candidate,
)
from agentic_data_platform.tools.builtin import build_tool_registry


def _semantic_yaml(tmp_path):
    path = tmp_path / "hospitality.yml"
    path.write_text(
        """
name: hospitality
description: Hospitality business semantics
tables:
  - name: stays
    description: Guest stays
    base_table:
      database: HOTEL
      schema: MART
      table: FACT_STAY
    primary_key:
      columns: [STAY_ID]
    dimensions:
      - name: property
        description: Hotel property
        expr: PROPERTY_NAME
        data_type: TEXT
        synonyms: [hotel]
    time_dimensions:
      - name: stay_date
        expr: STAY_DATE
        data_type: DATE
    facts:
      - name: room_revenue
        expr: ROOM_REVENUE
        data_type: NUMBER
    metrics:
      - name: occupied_rooms
        expr: SUM(OCCUPIED_ROOMS)
      - name: available_rooms
        expr: SUM(AVAILABLE_ROOMS)
relationships: []
metrics:
  - name: revpar
    description: Revenue per available room
    expr: SUM(stays.room_revenue) / stays.available_rooms
verified_queries:
  - name: revpar_by_property
    question: What is RevPAR by property?
    sql: SELECT property, SUM(room_revenue) / SUM(available_rooms) AS revpar FROM stays GROUP BY property
    verified_by: analytics-team
    verified_at: 1788976800
    use_as_onboarding_question: true
module_custom_instructions:
  sql_generation: Use occupied stays only.
"""
    )
    return path


def test_semantic_yaml_ingest_search_and_verified_query_evaluation(tmp_path):
    registry = SemanticRegistry(tmp_path / "semantic.db")
    resource = registry.ingest_yaml(_semantic_yaml(tmp_path))

    assert resource["name"] == "hospitality"
    assert resource["counts"] == {"elements": 7, "relationships": 0, "verified_queries": 1}
    assert {item["kind"] for item in resource["elements"]} >= {
        "table",
        "dimension",
        "time_dimension",
        "fact",
        "metric",
        "derived_metric",
    }

    search = registry.search("revenue available room")
    assert search
    assert any(item["name"] == "revpar" for item in search)

    verified = registry.find_verified("show RevPAR by property")
    assert verified[0]["name"] == "revpar_by_property"
    assert verified[0]["onboarding"] is True

    exact = evaluate_candidate(
        registry,
        question="What is RevPAR by property?",
        candidate_sql=verified[0]["sql"],
    )
    assert exact["status"] == "PASS"
    assert exact["best_match"]["exact_sql"] is True

    partial = evaluate_candidate(
        registry,
        question="What is RevPAR by property?",
        candidate_sql="SELECT COUNT(*) FROM stays",
    )
    assert partial["status"] == "PARTIAL"
    assert partial["best_match"]["table_overlap"] == 1.0


class SemanticFixture:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def __call__(self, sql: str):
        self.sql.append(sql)
        if sql.startswith("SHOW SEMANTIC VIEWS"):
            return {
                "rows": (
                    {
                        "name": "HOSPITALITY",
                        "database_name": "HOTEL",
                        "schema_name": "SEMANTIC",
                    },
                )
            }
        if sql.startswith("DESC SEMANTIC VIEW"):
            return {
                "rows": (
                    {
                        "object_kind": None,
                        "object_name": None,
                        "parent_entity": None,
                        "property": "COMMENT",
                        "property_value": "Hospitality metrics",
                    },
                    {
                        "object_kind": "TABLE",
                        "object_name": "stays",
                        "parent_entity": None,
                        "property": "BASE_TABLE",
                        "property_value": "HOTEL.MART.FACT_STAY",
                    },
                    {
                        "object_kind": "METRIC",
                        "object_name": "revpar",
                        "parent_entity": "stays",
                        "property": "EXPRESSION",
                        "property_value": "SUM(room_revenue) / SUM(available_rooms)",
                    },
                    {
                        "object_kind": "AI_VERIFIED_QUERY",
                        "object_name": "revpar_total",
                        "parent_entity": None,
                        "property": "QUESTION",
                        "property_value": "What is total RevPAR?",
                    },
                    {
                        "object_kind": "AI_VERIFIED_QUERY",
                        "object_name": "revpar_total",
                        "parent_entity": None,
                        "property": "SQL",
                        "property_value": "SELECT SUM(room_revenue)/SUM(available_rooms) FROM stays",
                    },
                )
            }
        raise AssertionError(sql)


def test_snowflake_semantic_adapter_discovers_describes_and_syncs(tmp_path):
    fixture = SemanticFixture()
    connector = SnowflakeConnector(
        fixture,
        SnowflakeConfig(database="HOTEL", schema="SEMANTIC"),
    )
    registry = SemanticRegistry(tmp_path / "semantic.db")
    adapter = SnowflakeSemanticAdapter(connector)

    result = adapter.sync(registry, database="HOTEL", schema="SEMANTIC")

    assert result["status"] == "PASS"
    assert result["synced"] == 1
    resource = registry.show("HOTEL.SEMANTIC.HOSPITALITY")
    assert resource["provider"] == "snowflake-semantic-view"
    assert resource["description"] == "Hospitality metrics"
    assert any(item["name"] == "revpar" for item in resource["elements"])
    assert resource["verified_queries"][0]["question"] == "What is total RevPAR?"
    assert fixture.sql[0] == "SHOW SEMANTIC VIEWS IN SCHEMA HOTEL.SEMANTIC"


def test_cortex_analyst_request_supports_multi_view_routing_and_offline_skip():
    payload = build_analyst_request(
        "Why did RevPAR fall?",
        ["HOTEL.SEMANTIC.HOSPITALITY", "HOTEL.SEMANTIC.FINANCE"],
    )

    assert [item["semantic_view"] for item in payload["semantic_models"]] == [
        "HOTEL.SEMANTIC.HOSPITALITY",
        "HOTEL.SEMANTIC.FINANCE",
    ]
    assert payload["messages"][-1]["content"][0]["text"] == "Why did RevPAR fall?"

    result = CortexAnalystAdapter(account_url="", token="").run(
        "Why did RevPAR fall?",
        ["HOTEL.SEMANTIC.HOSPITALITY"],
    )
    assert result["status"] == "SKIP_EXTERNAL"
    assert result["request"]["semantic_models"][0]["semantic_view"].endswith("HOSPITALITY")


def test_semantic_surfaces_are_registered_and_exposed():
    registry = build_tool_registry()
    for name in (
        "semantic_ingest_yaml",
        "semantic_list",
        "semantic_show",
        "semantic_registry_search",
        "semantic_verified_search",
        "semantic_evaluate",
        "semantic_evaluate_batch",
        "semantic_snowflake_sync",
        "cortex_analyst_plan",
        "cortex_analyst_run",
    ):
        assert registry.describe(name).name == name

    assert DOMAIN_CLI_TOOLS["semantic"]["search"] == "semantic_registry_search"
    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert set(domains.json()["semantic"]) == {
        "ingest-yaml",
        "list",
        "show",
        "search",
        "verified-search",
        "evaluate",
        "evaluate-batch",
        "snowflake-sync",
        "analyst-plan",
        "analyst-run",
    }
