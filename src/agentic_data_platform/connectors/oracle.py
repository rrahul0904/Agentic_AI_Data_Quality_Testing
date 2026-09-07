from __future__ import annotations

from typing import Any, Callable

from agentic_data_platform.connectors._common import execute, identifier, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class OracleConnector(DataPlatformConnector):
    platform = "oracle"

    def __init__(self, executor: Callable[[str], Any] | Any) -> None:
        self._executor = executor

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
            ConnectorCapability.GET_DDL,
        }

    def _read(self, sql: str) -> QueryResult:
        return query_result(execute(self._executor, sql))

    def list_schemas(self) -> list[SchemaMetadata]:
        rows = self._read("SELECT username AS schema_name FROM all_users ORDER BY username").rows
        return [SchemaMetadata(str(row["schema_name"])) for row in rows]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(
            "SELECT owner AS schema_name, table_name AS name, 'TABLE' AS object_type "
            f"FROM all_tables WHERE owner = UPPER({_literal(schema)}) ORDER BY table_name"
        ).rows
        return [TableMetadata(str(row["name"]), str(row["schema_name"]), object_type="table") for row in rows]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(
            "SELECT column_name AS name, data_type, nullable, column_id AS ordinal_position, "
            "data_precision AS numeric_precision, data_scale AS numeric_scale, data_default AS column_default "
            "FROM all_tab_columns "
            f"WHERE owner = UPPER({_literal(schema)}) AND table_name = UPPER({_literal(table)}) "
            "ORDER BY column_id"
        ).rows
        columns = tuple(
            ColumnMetadata(
                str(row["name"]),
                str(row["data_type"]),
                str(row.get("nullable", "Y")).upper() == "Y",
                int(row["ordinal_position"]) if row.get("ordinal_position") is not None else None,
                int(row["numeric_precision"]) if row.get("numeric_precision") is not None else None,
                int(row["numeric_scale"]) if row.get("numeric_scale") is not None else None,
                str(row["column_default"]).strip() if row.get("column_default") is not None else None,
            )
            for row in rows
        )
        return TableMetadata(table, schema, columns=columns)

    def get_ddl(self, schema: str, table: str) -> str:
        owner = identifier(schema.upper())
        name = identifier(table.upper())
        rows = self._read(
            f"SELECT DBMS_METADATA.GET_DDL('TABLE', {_literal(name)}, {_literal(owner)}) AS ddl FROM dual"
        ).rows
        if not rows:
            raise KeyError(f"Oracle table not found: {schema}.{table}")
        return str(rows[0]["ddl"])

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            self._read("EXPLAIN PLAN FOR " + sql)
            plan = self._read("SELECT plan_table_output AS plan FROM TABLE(DBMS_XPLAN.DISPLAY())")
            return DryRunResult(True, metadata={"plan": list(plan.rows)})
        except Exception as exc:
            return DryRunResult(False, warnings=("Oracle EXPLAIN failed",), metadata={"error": str(exc)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)
