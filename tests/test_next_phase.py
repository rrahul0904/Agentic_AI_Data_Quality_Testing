from __future__ import annotations

from pathlib import Path

import pytest

from agentic_data_platform.api.app import create_app
from agentic_data_platform.models import ActorMode, Environment, Risk, ToolRequest
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.platform.discovery import PlatformDiscovery
from agentic_data_platform.platform.graph import PlatformAssetGraph
from agentic_data_platform.quality.reconciliation import reconcile_row_count
from agentic_data_platform.quality.store import QualityResult, SQLiteQualityStore
from agentic_data_platform.sql.intelligence import column_lineage, review_sql
from agentic_data_platform.metadata.index import MetadataIndex
from agentic_data_platform.connectors.warehouse import ConnectorWarehouseAdapter
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


ROOT = Path(__file__).resolve().parents[1]
HOSPITALITY = ROOT / "hospitality-snowflake-data-platform"


def test_platform_discovery_counts_hospitality_assets():
    result = PlatformDiscovery(HOSPITALITY).discover()
    assert result["sources"] == {"oracle": True, "oracle_tables": 144, "postgres": True, "postgres_tables": 157, "files": True, "file_feeds": 18}
    assert result["dbt"]["models"] >= 64
    assert result["airflow"]["dag_count"] >= 46
    assert result["snowflake"]["static_config"] is True


def test_dbt_manifest_lineage_and_impact():
    registry = build_tool_registry()
    summary = registry.invoke(ToolInvocation(
        ToolRequest("dbt_manifest_summary", "read", Environment.DEV, Risk.READ_ONLY, args={"project": str(HOSPITALITY)}),
        "test-summary",
    ))
    assert summary["resource_counts"]["model"] >= 64
    lineage = registry.invoke(ToolInvocation(
        ToolRequest("dbt_lineage", "read", Environment.DEV, Risk.READ_ONLY, args={"project": str(HOSPITALITY), "node": "fact_reservation"}),
        "test-lineage",
    ))
    assert any(item["name"] == "int_reservation_lifecycle" for item in lineage["upstream"])
    impact = registry.invoke(ToolInvocation(
        ToolRequest("dbt_impact", "read", Environment.DEV, Risk.READ_ONLY, args={"project": str(HOSPITALITY), "node": "stg_oracle_reservation"}),
        "test-impact",
    ))
    assert impact["affected_marts"]


def test_airflow_inventory_and_reservation_writers():
    airflow = AirflowProject.scan(HOSPITALITY)
    assert airflow.health()["status"] == "PASS"
    assert "07_oracle_reservation_header_ingest" in airflow.summary()["dags"]
    assert airflow.find_writing("RAW_INGESTION_EVENTS")


def test_cross_system_lineage_includes_source_airflow_raw_and_dbt():
    graph = PlatformAssetGraph.build(HOSPITALITY)
    lineage = graph.lineage("fact_reservation")
    names = {item["name"] for item in lineage["upstream"]}
    assert "oracle.RESERVATION" in names
    assert "07_oracle_reservation_header_ingest" in names
    assert "HOSPITALITY_DW.RAW.ORACLE_RESERVATION" in names
    assert graph.impact("stg_oracle_reservation")["affected_marts"]


def test_reconciliation_is_fail_closed_and_tolerance_aware():
    assert reconcile_row_count(10000, 9998)["status"] == "FAIL"
    assert reconcile_row_count(10000, 9998, percentage_tolerance=0.02)["status"] == "PASS"


def test_quality_store_persists_local_snowflake_shape(tmp_path):
    store = SQLiteQualityStore(tmp_path / "quality.sqlite")
    store.initialize()
    run_id = store.start_run("reservation-quality")
    result = QualityResult("reservation_pk_unique", run_id, "local", "RAW", "RAW.RESERVATION", "duplicate_key", "ERROR", "FAIL", 2, 0)
    store.save_result(result)
    store.save_reconciliation(run_id, reconcile_row_count(10, 9))
    store.complete_run(run_id, "FAIL")
    assert store.get_run(run_id)["status"] == "FAIL"
    assert store.list_results(run_id)[0]["check_id"] == "reservation_pk_unique"


def test_actor_modes_cannot_escalate_to_mutation():
    registry = build_tool_registry()
    definition = registry.describe("migration_convert_model")
    request = ToolRequest(definition.name, "convert", Environment.DEV, definition.risk, args={"sql": "select 1"})
    with pytest.raises(PermissionError):
        registry.invoke(ToolInvocation(request, "analyst", actor_mode=ActorMode.ANALYST))


def test_shiftforge_adapter_is_structured():
    registry = build_tool_registry()
    fixture = ROOT / "shiftforge" / "examples" / "revinate"
    result = registry.invoke(ToolInvocation(
        ToolRequest("migration_scan", "scan", Environment.DEV, Risk.READ_ONLY, args={"project": str(fixture)}),
        "migration-scan",
    ))
    assert result["models"] == 2
    converted = registry.invoke(ToolInvocation(
        ToolRequest("migration_convert_model", "convert", Environment.DEV, registry.describe("migration_convert_model").risk, args={"sql": "SELECT IFNULL(a, 0) AS value FROM t", "model_name": "model.sql"}),
        "migration-convert",
    ))
    assert converted["converted_sql"]


def test_tool_api_exposes_registry(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    tools = client.get("/tools")
    assert tools.status_code == 200
    assert any(item["name"] == "platform_discover" for item in tools.json())
    response = client.post("/tools/reconcile_row_count", json={"args": {"source_value": 2, "target_value": 1}})
    assert response.status_code == 200
    assert response.json()["status"] == "FAIL"


def test_sql_ast_review_and_column_lineage():
    review = review_sql("SELECT * FROM orders o JOIN payments p ON o.id = p.order_id")
    assert review["parseable"] is True
    assert any(item["rule_id"] == "SELECT_STAR" for item in review["findings"])
    lineage = column_lineage("SELECT o.id AS reservation_id, o.amount / NULLIF(o.nights, 0) AS nightly FROM orders o")
    assert {item["target_column"] for item in lineage["mappings"]} == {"reservation_id", "nightly"}
    assert lineage["mappings"][0]["sources"][0]["column"] == "id"


def test_metadata_index_search_and_pii(tmp_path):
    index = MetadataIndex(tmp_path / "metadata.sqlite")
    index.upsert_asset("t1", "warehouse_table", "RAW.RESERVATION")
    index.upsert_column("t1", "guest_email", "VARCHAR", pii=True)
    assert index.search_assets("reservation")[0]["name"] == "RAW.RESERVATION"
    assert index.search_columns("email", pii_only=True)[0]["asset_name"] == "RAW.RESERVATION"


def test_migration_inventory_and_blockers_are_structured():
    registry = build_tool_registry()
    fixture = ROOT / "shiftforge" / "examples" / "revinate"
    inventory = registry.invoke(ToolInvocation(ToolRequest("migration_inventory", "inventory", Environment.DEV, Risk.READ_ONLY, args={"project": str(fixture)}), "migration-inventory"))
    assert inventory["models"] == 2
    findings = registry.invoke(ToolInvocation(ToolRequest("migration_show_findings", "findings", Environment.DEV, Risk.READ_ONLY, args={"project": str(fixture)}), "migration-findings"))
    assert "findings" in findings and isinstance(findings["findings"], list)


def test_warehouse_facade_preserves_read_only_connector_contract():
    from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata
    from agentic_data_platform.connectors.base import DataPlatformConnector

    class Fake(DataPlatformConnector):
        platform = "fake"
        def capabilities(self): return set()
        def list_schemas(self): return [SchemaMetadata("PUBLIC", "DB")]
        def list_tables(self, schema): return [TableMetadata("T", schema, "DB")]
        def describe_table(self, schema, table): return TableMetadata(table, schema, "DB", columns=(ColumnMetadata("ID", "INT", False),))
        def dry_run_sql(self, sql): return DryRunResult(True)
        def execute_read(self, sql): return QueryResult(["x"], [(1,)])
        def list_catalogs(self): return ["DB"]

    adapter = ConnectorWarehouseAdapter(Fake())
    assert adapter.ping() and adapter.databases() == ["DB"]
    assert adapter.columns("PUBLIC", "T")[0].name == "ID"
