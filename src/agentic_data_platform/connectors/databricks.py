from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from agentic_data_platform.connectors._common import execute, identifier, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


@dataclass(frozen=True)
class DatabricksConfig:
    host: str | None = None
    token: str | None = field(default=None, repr=False)
    http_path: str | None = None
    catalog: str | None = None

    @classmethod
    def from_env(cls) -> "DatabricksConfig":
        return cls(*(os.getenv(f"ADE_DATABRICKS_{name}") for name in ("HOST", "TOKEN", "HTTP_PATH", "CATALOG")))


class DatabricksConnector(DataPlatformConnector):
    platform = "databricks"

    def __init__(self, executor: Callable[[str], Any] | Any, config: DatabricksConfig | None = None) -> None:
        self._executor = executor
        self.config = config or DatabricksConfig.from_env()

    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.LIST_CATALOGS, ConnectorCapability.LIST_SCHEMAS, ConnectorCapability.LIST_TABLES, ConnectorCapability.DESCRIBE_TABLE, ConnectorCapability.QUERY_READ, ConnectorCapability.QUERY_DRY_RUN}

    def _read(self, sql: str) -> QueryResult:
        return query_result(execute(self._executor, sql))

    def list_catalogs(self) -> list[str]:
        return [str(row["catalog"]) for row in self._read("SHOW CATALOGS").rows]

    def list_schemas(self) -> list[SchemaMetadata]:
        catalog = identifier(self.config.catalog or "")
        return [SchemaMetadata(str(row["databaseName"]), catalog) for row in self._read(f"SHOW SCHEMAS IN {catalog}").rows]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        catalog = identifier(self.config.catalog or "")
        rows = self._read(f"SHOW TABLES IN {catalog}.{identifier(schema)}").rows
        return [TableMetadata(str(row["tableName"]), schema, catalog, "view" if row.get("isTemporary") else "table") for row in rows]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        catalog = identifier(self.config.catalog or "")
        rows = self._read(f"DESCRIBE TABLE {catalog}.{identifier(schema)}.{identifier(table)}").rows
        columns = tuple(ColumnMetadata(str(row["col_name"]), str(row["data_type"]), str(row.get("comment", "")).upper() != "NOT NULL") for row in rows if not str(row["col_name"]).startswith("#"))
        return TableMetadata(table, schema, catalog, columns=columns)

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            self._read(f"EXPLAIN {sql}")
            return DryRunResult(True)
        except Exception as exc:
            return DryRunResult(False, warnings=("Databricks explain failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)
