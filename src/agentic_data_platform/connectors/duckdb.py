from __future__ import annotations

from typing import Any

from agentic_data_platform.connectors._common import query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class DuckDBConnector(DataPlatformConnector):
    platform = "duckdb"

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.LIST_CATALOGS,
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
            ConnectorCapability.GET_DDL,
        }

    def _read(self, sql: str) -> QueryResult:
        return query_result(self._connection.execute(sql))

    def list_catalogs(self) -> list[str]:
        return [str(row["database_name"]) for row in self._read("SELECT database_name FROM duckdb_databases()").rows]

    def list_schemas(self) -> list[SchemaMetadata]:
        rows = self._read("SELECT catalog_name, schema_name FROM information_schema.schemata ORDER BY schema_name").rows
        return [SchemaMetadata(str(row["schema_name"]), str(row["catalog_name"])) for row in rows]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(
            "SELECT table_catalog, table_name, table_type FROM information_schema.tables "
            f"WHERE table_schema = {_literal(schema)} ORDER BY table_name"
        ).rows
        return [
            TableMetadata(str(row["table_name"]), schema, str(row["table_catalog"]), str(row["table_type"]).lower())
            for row in rows
        ]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(
            "SELECT table_catalog, column_name, data_type, is_nullable, ordinal_position, column_default "
            "FROM information_schema.columns "
            f"WHERE table_schema = {_literal(schema)} AND table_name = {_literal(table)} "
            "ORDER BY ordinal_position"
        ).rows
        catalog = str(rows[0]["table_catalog"]) if rows else None
        columns = tuple(
            ColumnMetadata(
                str(row["column_name"]),
                str(row["data_type"]),
                str(row["is_nullable"]).upper() == "YES",
                int(row["ordinal_position"]) if row.get("ordinal_position") is not None else None,
                default=str(row["column_default"]) if row.get("column_default") is not None else None,
            )
            for row in rows
        )
        return TableMetadata(table, schema, catalog, columns=columns)

    def get_ddl(self, schema: str, table: str) -> str:
        rows = self._read(
            "SELECT sql FROM duckdb_tables() "
            f"WHERE schema_name = {_literal(schema)} AND table_name = {_literal(table)}"
        ).rows
        if rows:
            return str(rows[0]["sql"])
        rows = self._read(
            "SELECT sql FROM duckdb_views() "
            f"WHERE schema_name = {_literal(schema)} AND view_name = {_literal(table)}"
        ).rows
        if rows:
            return str(rows[0]["sql"])
        raise KeyError(f"DuckDB object not found: {schema}.{table}")

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            plan = self._read(f"EXPLAIN {sql}")
            return DryRunResult(True, metadata={"plan": list(plan.rows)})
        except Exception as exc:
            return DryRunResult(False, warnings=("DuckDB EXPLAIN failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)
