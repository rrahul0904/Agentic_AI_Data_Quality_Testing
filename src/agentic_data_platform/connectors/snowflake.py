from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from agentic_data_platform.connectors._common import execute, identifier, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str | None = None
    user: str | None = None
    database: str | None = None
    schema: str | None = None
    warehouse: str | None = None
    role: str | None = None

    @classmethod
    def from_env(cls) -> "SnowflakeConfig":
        return cls(*(os.getenv(f"ADE_SNOWFLAKE_{name}") for name in ("ACCOUNT", "USER", "DATABASE", "SCHEMA", "WAREHOUSE", "ROLE")))


class SnowflakeConnector(DataPlatformConnector):
    platform = "snowflake"

    def __init__(self, executor: Callable[[str], Any] | Any, config: SnowflakeConfig | None = None) -> None:
        self._executor = executor
        self.config = config or SnowflakeConfig.from_env()

    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.LIST_SCHEMAS, ConnectorCapability.LIST_TABLES, ConnectorCapability.DESCRIBE_TABLE, ConnectorCapability.QUERY_READ, ConnectorCapability.QUERY_DRY_RUN, ConnectorCapability.GET_DDL, ConnectorCapability.GET_QUERY_HISTORY}

    def _read(self, sql: str) -> QueryResult:
        return query_result(execute(self._executor, sql))

    def list_schemas(self) -> list[SchemaMetadata]:
        database = identifier(self.config.database or "")
        return [SchemaMetadata(str(row["name"]), database) for row in self._read(f"SHOW SCHEMAS IN DATABASE {database}").rows]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(f"SHOW TABLES IN SCHEMA {identifier(schema)}").rows
        return [TableMetadata(str(row.get("name")), schema, self.config.database, str(row.get("kind", "table")).lower()) for row in rows]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(f"DESC TABLE {identifier(schema)}.{identifier(table)}").rows
        columns = tuple(ColumnMetadata(str(row["name"]), str(row["type"]), str(row.get("null?", "Y")).upper() != "N") for row in rows if row.get("kind", "COLUMN") == "COLUMN")
        return TableMetadata(table, schema, self.config.database, columns=columns)

    def get_ddl(self, schema: str, table: str) -> str:
        row = self._read(f"SELECT GET_DDL('TABLE', '{identifier(schema)}.{identifier(table)}') AS ddl").rows[0]
        return str(row["ddl"])

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            self._read(f"EXPLAIN USING TEXT {sql}")
            return DryRunResult(True)
        except Exception as exc:
            return DryRunResult(False, warnings=("Snowflake explain failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)
