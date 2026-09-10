from __future__ import annotations

import sqlite3

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import (
    ColumnMetadata,
    DryRunResult,
    QueryResult,
    SchemaMetadata,
    TableMetadata,
)
from agentic_data_platform.metadata.service import MetadataService
from agentic_data_platform.models import Environment, Risk, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation
from agentic_data_platform.advanced_capabilities import sql_playground


class FixtureConnector(DataPlatformConnector):
    def __init__(
        self,
        platform: str,
        catalog: str,
        schema: str,
        table: str,
        *,
        comment: str,
        columns: tuple[ColumnMetadata, ...],
    ) -> None:
        self.platform = platform
        self.catalog = catalog
        self.schema = schema
        self.table = table
        self.comment = comment
        self.columns = columns

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
        }

    def list_schemas(self) -> list[SchemaMetadata]:
        return [SchemaMetadata(self.schema, self.catalog)]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        return [
            TableMetadata(
                self.table,
                schema,
                self.catalog,
                columns=self.columns,
                comment=self.comment,
            )
        ]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        return TableMetadata(
            table,
            schema,
            self.catalog,
            columns=self.columns,
            comment=self.comment,
        )

    def dry_run_sql(self, sql: str) -> DryRunResult:
        return DryRunResult(True)

    def execute_read(self, sql: str) -> QueryResult:
        return QueryResult((), ())


def test_object_search_uses_real_multi_warehouse_metadata_catalog(tmp_path):
    database = tmp_path / "metadata.db"
    metadata = MetadataService(database)
    metadata.refresh(
        "snowflake-prod",
        FixtureConnector(
            "snowflake",
            "PROD",
            "MART",
            "FACT_RESERVATION",
            comment="reservation revenue fact with nightly evidence",
            columns=(
                ColumnMetadata("reservation_id", "NUMBER"),
                ColumnMetadata("revenue", "NUMBER"),
            ),
        ),
    )
    metadata.refresh(
        "postgres-operational",
        FixtureConnector(
            "postgres",
            "booking",
            "public",
            "reservation_events",
            comment="operational reservation event stream",
            columns=(
                ColumnMetadata("reservation_id", "BIGINT"),
                ColumnMetadata("event_type", "TEXT"),
            ),
        ),
    )
    metadata.refresh(
        "databricks-lakehouse",
        FixtureConnector(
            "databricks",
            "main",
            "silver",
            "guest_profiles",
            comment="guest profile enrichment",
            columns=(
                ColumnMetadata("guest_id", "BIGINT"),
                ColumnMetadata("segment", "STRING"),
            ),
        ),
    )

    registry = build_tool_registry()
    result = registry.invoke(
        ToolInvocation(
            ToolRequest(
                tool="warehouse_object_search",
                operation="warehouse_object_search",
                environment=Environment.DEV,
                risk=Risk.READ_ONLY,
                args={
                    "metadata_database": str(database),
                    "query": "reservation revenue",
                    "lineage_by_object": {
                        "PROD.MART.FACT_RESERVATION": {
                            "downstream": ["PROD.MART.REVPAR"]
                        }
                    },
                    "limit": 10,
                },
            ),
            run_id="cross-warehouse-search",
        )
    )

    assert result["status"] == "PASS"
    assert result["inventory_source"] == "metadata_service"
    assert result["candidate_count"] == 3
    assert result["results"][0]["qualified_name"] == "PROD.MART.FACT_RESERVATION"
    assert result["results"][0]["connection_name"] == "snowflake-prod"
    assert result["results"][0]["score_components"]["lineage_neighbor_count"] == 1
    assert {"snowflake", "postgres"} <= set(result["platforms"])
    assert result["inventory_fingerprint"]
    assert result["search_fingerprint"]


def test_object_search_can_match_column_names_across_warehouses(tmp_path):
    database = tmp_path / "metadata.db"
    metadata = MetadataService(database)
    metadata.refresh(
        "snowflake",
        FixtureConnector(
            "snowflake",
            "PROD",
            "MART",
            "ORDERS",
            comment="orders",
            columns=(ColumnMetadata("guest_email", "VARCHAR"),),
        ),
    )
    metadata.refresh(
        "postgres",
        FixtureConnector(
            "postgres",
            "booking",
            "public",
            "CUSTOMERS",
            comment="customers",
            columns=(ColumnMetadata("customer_email", "TEXT"),),
        ),
    )

    registry = build_tool_registry()
    result = registry.invoke(
        ToolInvocation(
            ToolRequest(
                tool="warehouse_object_search",
                operation="warehouse_object_search",
                environment=Environment.DEV,
                risk=Risk.READ_ONLY,
                args={
                    "metadata_database": str(database),
                    "query": "email",
                },
            ),
            run_id="column-search",
        )
    )

    assert result["matched_count"] == 2
    assert set(result["platforms"]) == {"postgres", "snowflake"}


def test_sql_playground_records_policy_optimization_plan_and_cost_evidence(tmp_path):
    database = tmp_path / "playground.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("create table sales(day text, revenue integer)")
        connection.executemany(
            "insert into sales values (?, ?)",
            [("Mon", 10), ("Tue", 20), ("Wed", 30)],
        )
        connection.commit()
    finally:
        connection.close()

    result = sql_playground(
        "select day, revenue from sales where revenue >= 20 order by revenue",
        dialect="sqlite",
        sqlite_database=str(database),
        max_rows=50,
    )

    assert result["status"] == "PASS"
    assert result["execution"] == "PASS"
    assert result["policy"]["read_only"] is True
    assert result["policy"]["single_statement"] is True
    assert result["policy"]["policy_fingerprint"]
    assert result["lineage"]["tables"] == ["sales"]
    assert result["lineage"]["lineage_fingerprint"]
    assert result["optimization"]["predicate_present"] is True
    assert result["optimization"]["optimization_fingerprint"]
    assert result["cost_evidence"]["engine"] == "sqlite"
    assert result["cost_evidence"]["estimated_cost_usd"] == 0.0
    assert result["cost_evidence"]["query_plan"]
    assert result["cost_evidence"]["query_plan_fingerprint"]
    assert result["cost_evidence"]["cost_fingerprint"]
    assert result["row_count_returned"] == 2


def test_sql_playground_reports_scan_risk_and_recommendations_without_execution():
    result = sql_playground(
        "select * from fact_reservation cross join dim_date",
        dialect="snowflake",
    )

    assert result["status"] == "PASS"
    assert result["execution"] == "NOT_RUN_EXTERNAL"
    assert result["optimization"]["select_star"] is True
    assert result["optimization"]["cross_join_count"] == 1
    assert result["cost_evidence"]["scan_risk"] == "high"
    assert result["cost_evidence"]["estimated_cost_usd"] is None
    assert result["optimization"]["recommendations"]


def test_sql_playground_blocks_hidden_mutation_and_multiple_statements(tmp_path):
    database = tmp_path / "guard.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("create table sales(value integer)")
        connection.commit()
    finally:
        connection.close()

    mutation = sql_playground(
        "delete from sales",
        dialect="sqlite",
        sqlite_database=str(database),
    )
    multiple = sql_playground(
        "select * from sales; select * from sales",
        dialect="sqlite",
        sqlite_database=str(database),
    )

    assert mutation["status"] == "BLOCKED_POLICY"
    assert mutation["policy"]["mutation_class"] == "mutating"
    assert multiple["status"] == "BLOCKED_POLICY"
    assert multiple["policy"]["single_statement"] is False
