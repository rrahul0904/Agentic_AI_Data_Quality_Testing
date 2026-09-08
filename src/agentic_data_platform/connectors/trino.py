from __future__ import annotations

from typing import Any, Callable

from agentic_data_platform.connectors._common import execute, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


def _identifier(value: str) -> str:
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$" for ch in value):
        raise ValueError("invalid Trino identifier")
    return value


class TrinoConnector(DataPlatformConnector):
    platform = "trino"

    def __init__(self, executor: Callable[[str], Any] | Any, *, catalog: str) -> None:
        self._executor = executor
        self.catalog = _identifier(catalog)

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
        rows = self._read("SHOW CATALOGS").rows
        return [str(next(iter(row.values()))) for row in rows if row]

    def list_schemas(self) -> list[SchemaMetadata]:
        rows = self._read(f"SHOW SCHEMAS FROM {self.catalog}").rows
        return [SchemaMetadata(str(next(iter(row.values()))), self.catalog) for row in rows if row]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        schema_name = _identifier(schema)
        rows = self._read(f"SHOW TABLES FROM {self.catalog}.{schema_name}").rows
        return [TableMetadata(str(next(iter(row.values()))), schema_name, self.catalog) for row in rows if row]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        schema_name = _identifier(schema)
        table_name = _identifier(table)
        rows = self._read(f"DESCRIBE {self.catalog}.{schema_name}.{table_name}").rows
        columns = []
        for position, row in enumerate(rows, 1):
            values = list(row.values())
            if not values:
                continue
            columns.append(
                ColumnMetadata(
                    str(values[0]),
                    str(values[1]) if len(values) > 1 else "UNKNOWN",
                    True,
                    position,
                )
            )
        return TableMetadata(table_name, schema_name, self.catalog, columns=tuple(columns))

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            rows = self._read("EXPLAIN " + sql)
            return DryRunResult(True, metadata={"plan": list(rows.rows)})
        except Exception as exc:
            return DryRunResult(False, warnings=("Trino EXPLAIN failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)
