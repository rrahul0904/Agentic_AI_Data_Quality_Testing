from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.semantic import SemanticRegistry, ingest_dbt_semantic_project, ingest_lookml_project
from agentic_data_platform.tools.builtin import build_tool_registry


def test_dbt_metricflow_semantic_project_ingestion(tmp_path):
    project = tmp_path / "dbt_project"
    project.mkdir()
    (project / "semantic.yml").write_text(
        """
semantic_models:
  - name: stays
    description: Stay grain semantics
    model: ref("fact_stay")
    defaults:
      agg_time_dimension: stay_date
    entities:
      - name: stay
        type: primary
        expr: stay_id
      - name: property
        type: foreign
        expr: property_id
    dimensions:
      - name: stay_date
        type: time
        type_params:
          time_granularity: day
      - name: channel
        type: categorical
    measures:
      - name: room_revenue
        agg: sum
      - name: occupied_rooms
        agg: sum
metrics:
  - name: revpar
    description: Revenue per available room
    type: ratio
    type_params:
      numerator: room_revenue
      denominator: available_rooms
saved_queries:
  - name: property_daily_kpis
    description: Daily KPI query
    query_params:
      metrics: [revpar]
      group_by: [Dimension("property")]
"""
    )
    registry = SemanticRegistry(tmp_path / "semantic.db")

    result = ingest_dbt_semantic_project(registry, project)

    assert result["provider"] == "dbt-semantic-layer"
    assert result["counts"]["elements"] == 9
    kinds = {item["kind"] for item in result["elements"]}
    assert {"semantic_model", "entity", "time_dimension", "dimension", "measure", "metric", "saved_query"} <= kinds
    assert result["relationships"][0]["relationship"] == "metricflow_foreign_entity"
    assert result["metadata"]["semantic_model_count"] == 1
    assert result["metadata"]["metric_count"] == 1
    assert result["metadata"]["saved_query_count"] == 1


def test_lookml_project_ingestion_preserves_views_fields_explores_and_joins(tmp_path):
    project = tmp_path / "looker"
    project.mkdir()
    (project / "stays.view.lkml").write_text(
        """
view: stays {
  sql_table_name: HOTEL.MART.FACT_STAY ;;
  dimension: stay_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.STAY_ID ;;
  }
  dimension: property_id {
    type: string
    sql: ${TABLE}.PROPERTY_ID ;;
  }
  measure: room_revenue {
    type: sum
    sql: ${TABLE}.ROOM_REVENUE ;;
  }
}
"""
    )
    (project / "hospitality.model.lkml").write_text(
        """
explore: stays {
  join: property {
    type: left_outer
    relationship: many_to_one
    sql_on: ${stays.property_id} = ${property.property_id} ;;
  }
}
"""
    )
    registry = SemanticRegistry(tmp_path / "semantic.db")

    result = ingest_lookml_project(registry, project)

    assert result["provider"] == "lookml"
    assert result["metadata"]["view_count"] == 1
    assert result["metadata"]["explore_count"] == 1
    view = next(item for item in result["elements"] if item["kind"] == "view")
    assert view["expression"] == "HOTEL.MART.FACT_STAY"
    stay_id = next(item for item in result["elements"] if item["name"] == "stay_id")
    assert stay_id["metadata"]["primary_key"] is True
    assert "${TABLE}.STAY_ID" in stay_id["expression"]
    relationship = result["relationships"][0]
    assert relationship["name"] == "stays.property"
    assert relationship["relationship"] == "many_to_one"
    assert "${stays.property_id}" in relationship["sql_on"]


def test_semantic_adapter_tools_cli_and_api_are_exposed():
    registry = build_tool_registry()
    assert registry.describe("semantic_ingest_dbt").name == "semantic_ingest_dbt"
    assert registry.describe("semantic_ingest_lookml").name == "semantic_ingest_lookml"
    assert DOMAIN_CLI_TOOLS["semantic"]["ingest-dbt"] == "semantic_ingest_dbt"
    assert DOMAIN_CLI_TOOLS["semantic"]["ingest-lookml"] == "semantic_ingest_lookml"

    client = TestClient(create_app())
    surface = client.get("/api/v1/domains")
    assert surface.status_code == 200
    assert "ingest-dbt" in surface.json()["semantic"]
    assert "ingest-lookml" in surface.json()["semantic"]
