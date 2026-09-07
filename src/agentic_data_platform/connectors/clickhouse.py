from __future__ import annotations

from typing import Any, Callable

from agentic_data_platform.connectors._common import execute, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class ClickHouseConnector(DataPlatformConnector):
    platform = "clickhouse"

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
            ConnectorCapability.GET_DDL,
            ConnectorCapability.GET_QUERY_HISTORY,
        }

    def _read(self, sql: str) -> QueryResult:
        return query_result(execute(self._executor, sql))

    def list_catalogs(self) -> list[str]:
        return [str(row["name"]) for row in self._read("SELECT name FROM system.databases ORDER BY name").rows]

    def list_schemas(self) -> list[SchemaMetadata]:
        return [SchemaMetadata(name, name) for name in self.list_catalogs()]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(
            "SELECT database, name, engine FROM system.tables "
            f"WHERE database = {_literal(schema)} ORDER BY name"
        ).rows
        return [
            TableMetadata(str(row["name"]), str(row["database"]), str(row["database"]), str(row["engine"]))
            for row in rows
        ]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(
            "SELECT database, table, name, type, position, default_expression "
            "FROM system.columns "
            f"WHERE database = {_literal(schema)} AND table = {_literal(table)} ORDER BY position"
        ).rows
        columns = tuple(
            ColumnMetadata(
                str(row["name"]),
                str(row["type"]),
                True,
                int(row["position"]) if row.get("position") is not None else None,
                default=str(row["default_expression"]) if row.get("default_expression") else None,
            )
            for row in rows
        )
        return TableMetadata(table, schema, schema, columns=columns)

    def get_ddl(self, schema: str, table: str) -> str:
        rows = self._read(
            "SELECT create_table_query AS ddl FROM system.tables "
            f"WHERE database = {_literal(schema)} AND name = {_literal(table)}"
        ).rows
        if not rows:
            raise KeyError(f"ClickHouse object not found: {schema}.{table}")
        return str(rows[0]["ddl"])

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            rows = self._read("EXPLAIN " + sql)
            return DryRunResult(True, metadata={"plan": list(rows.rows)})
        except Exception as exc:
            return DryRunResult(False, warnings=("ClickHouse EXPLAIN failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)

    def query_history(self, *, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        rows = self._read(
            "SELECT query_id, user, query_duration_ms, read_rows, read_bytes, result_rows, query "
            "FROM system.query_log WHERE type = 'QueryFinish' ORDER BY event_time DESC "
            f"LIMIT {max(1, min(int(limit), 10000))}"
        )
        return list(rows.rows)
