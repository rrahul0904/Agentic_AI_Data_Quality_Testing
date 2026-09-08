from __future__ import annotations

from typing import Any

from agentic_data_platform.connectors._common import query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class SQLiteConnector(DataPlatformConnector):
    platform = "sqlite"

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
        return [str(row["name"]) for row in self._read("PRAGMA database_list").rows]

    def list_schemas(self) -> list[SchemaMetadata]:
        return [SchemaMetadata(name, name) for name in self.list_catalogs()]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(
            f"SELECT name, type FROM {_quote(schema)}.sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).rows
        return [TableMetadata(str(row["name"]), schema, schema, str(row["type"])) for row in rows]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(f"PRAGMA {_quote(schema)}.table_info({_quote(table)})").rows
        columns = tuple(
            ColumnMetadata(
                str(row["name"]),
                str(row.get("type") or "ANY"),
                not bool(row.get("notnull")),
                int(row["cid"]) + 1 if row.get("cid") is not None else None,
                default=str(row["dflt_value"]) if row.get("dflt_value") is not None else None,
            )
            for row in rows
        )
        return TableMetadata(table, schema, schema, columns=columns)

    def get_ddl(self, schema: str, table: str) -> str:
        rows = self._read(
            f"SELECT sql FROM {_quote(schema)}.sqlite_master "
            f"WHERE name = '{table.replace(chr(39), chr(39)*2)}'"
        ).rows
        if not rows or rows[0].get("sql") is None:
            raise KeyError(f"SQLite object not found: {schema}.{table}")
        return str(rows[0]["sql"])

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            result = self._read("EXPLAIN QUERY PLAN " + sql)
            return DryRunResult(True, metadata={"plan": list(result.rows)})
        except Exception as exc:
            return DryRunResult(False, warnings=("SQLite EXPLAIN failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)
