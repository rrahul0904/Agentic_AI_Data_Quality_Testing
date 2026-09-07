from __future__ import annotations

from typing import Any, Callable

from agentic_data_platform.connectors._common import execute, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class InformationSchemaConnector(DataPlatformConnector):
    """DB-API connector for warehouses exposing SQL information_schema."""

    catalog_sql = "SELECT catalog_name AS catalog FROM information_schema.information_schema_catalog_name"
    schema_sql = "SELECT catalog_name AS catalog, schema_name AS schema FROM information_schema.schemata ORDER BY schema_name"

    def __init__(self, executor: Callable[[str], Any] | Any) -> None:
        self._executor = executor

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.LIST_CATALOGS,
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
        }

    def _read(self, sql: str) -> QueryResult:
        return query_result(execute(self._executor, sql))

    def list_catalogs(self) -> list[str]:
        return [str(row["catalog"]) for row in self._read(self.catalog_sql).rows if row.get("catalog") is not None]

    def list_schemas(self) -> list[SchemaMetadata]:
        return [
            SchemaMetadata(str(row["schema"]), str(row["catalog"]) if row.get("catalog") else None)
            for row in self._read(self.schema_sql).rows
        ]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(
            "SELECT table_catalog AS catalog, table_name AS name, table_type AS object_type "
            "FROM information_schema.tables "
            f"WHERE table_schema = {literal(schema)} ORDER BY table_name"
        ).rows
        return [
            TableMetadata(
                str(row["name"]), schema,
                str(row["catalog"]) if row.get("catalog") else None,
                str(row.get("object_type") or "table").casefold(),
            )
            for row in rows
        ]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(
            "SELECT table_catalog AS catalog, column_name AS name, data_type, is_nullable, "
            "ordinal_position, numeric_precision, numeric_scale, column_default "
            "FROM information_schema.columns "
            f"WHERE table_schema = {literal(schema)} AND table_name = {literal(table)} "
            "ORDER BY ordinal_position"
        ).rows
        columns = tuple(
            ColumnMetadata(
                str(row["name"]), str(row["data_type"]),
                str(row.get("is_nullable", "YES")).upper() == "YES",
                int(row["ordinal_position"]) if row.get("ordinal_position") is not None else None,
                int(row["numeric_precision"]) if row.get("numeric_precision") is not None else None,
                int(row["numeric_scale"]) if row.get("numeric_scale") is not None else None,
                str(row["column_default"]) if row.get("column_default") is not None else None,
            )
            for row in rows
        )
        catalog = str(rows[0]["catalog"]) if rows and rows[0].get("catalog") else None
        return TableMetadata(table, schema, catalog, columns=columns)

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            result = self._read("EXPLAIN " + sql)
            return DryRunResult(True, metadata={"plan": list(result.rows)})
        except Exception as exc:
            return DryRunResult(False, warnings=(f"{self.platform} EXPLAIN failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)


class PostgreSQLConnector(InformationSchemaConnector):
    platform = "postgres"
    catalog_sql = "SELECT datname AS catalog FROM pg_database WHERE datallowconn ORDER BY datname"


class RedshiftConnector(InformationSchemaConnector):
    platform = "redshift"
    catalog_sql = "SELECT datname AS catalog FROM pg_database WHERE datallowconn ORDER BY datname"


class MySQLConnector(InformationSchemaConnector):
    platform = "mysql"
    catalog_sql = "SELECT schema_name AS catalog FROM information_schema.schemata ORDER BY schema_name"
    schema_sql = "SELECT schema_name AS catalog, schema_name AS schema FROM information_schema.schemata ORDER BY schema_name"


class SQLServerConnector(InformationSchemaConnector):
    platform = "sqlserver"
    catalog_sql = "SELECT name AS catalog FROM sys.databases WHERE state = 0 ORDER BY name"
