"""Read-only relational warehouse connectors using native DB-API clients."""

from __future__ import annotations

from typing import Any

from agentic_data_platform.connectors._common import execute, query_result
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import (
    ColumnMetadata,
    DryRunResult,
    QueryResult,
    SchemaMetadata,
    TableMetadata,
)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _value(row: dict[str, Any], name: str, default: Any = None) -> Any:
    wanted = name.casefold()
    for key, value in row.items():
        if str(key).casefold() == wanted:
            return value
    return default


def _nullable(value: Any) -> bool:
    return str(value).strip().casefold() in {"yes", "y", "true", "1", "nullable"}


class InformationSchemaConnector(DataPlatformConnector):
    platform = "generic"

    catalog_sql: str | None = None
    schema_sql: str = (
        "SELECT catalog_name, schema_name FROM information_schema.schemata ORDER BY schema_name"
    )
    table_sql_template: str = (
        "SELECT table_catalog, table_schema, table_name, table_type "
        "FROM information_schema.tables WHERE table_schema = {schema} ORDER BY table_name"
    )
    column_sql_template: str = (
        "SELECT table_catalog, table_schema, table_name, column_name, data_type, is_nullable, "
        "ordinal_position, column_default FROM information_schema.columns "
        "WHERE table_schema = {schema} AND table_name = {table} ORDER BY ordinal_position"
    )
    explain_prefix = "EXPLAIN "

    def __init__(self, connection: Any, *, catalog: str | None = None) -> None:
        self.connection = connection
        self.catalog = catalog

    def _read(self, sql: str) -> QueryResult:
        return query_result(execute(self.connection, sql))

    def capabilities(self) -> set[ConnectorCapability]:
        capabilities = {
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
            ConnectorCapability.GET_DDL,
        }
        if self.catalog_sql:
            capabilities.add(ConnectorCapability.LIST_CATALOGS)
        return capabilities

    def list_catalogs(self) -> list[str]:
        if not self.catalog_sql:
            if self.catalog:
                return [self.catalog]
            return super().list_catalogs()
        rows = self._read(self.catalog_sql).rows
        values = []
        for row in rows:
            value = _value(row, "catalog_name")
            if value is None and row:
                value = next(iter(row.values()))
            if value is not None:
                values.append(str(value))
        return sorted(dict.fromkeys(values))

    def list_schemas(self) -> list[SchemaMetadata]:
        rows = self._read(self.schema_sql).rows
        result = []
        for row in rows:
            schema = _value(row, "schema_name")
            if schema is None and row:
                schema = list(row.values())[-1]
            if schema is None:
                continue
            catalog = _value(row, "catalog_name", self.catalog)
            result.append(SchemaMetadata(str(schema), str(catalog) if catalog is not None else None))
        return result

    def list_tables(self, schema: str) -> list[TableMetadata]:
        sql = self.table_sql_template.format(schema=_literal(schema), catalog=_literal(self.catalog or ""))
        rows = self._read(sql).rows
        result = []
        for row in rows:
            name = _value(row, "table_name")
            if name is None:
                continue
            result.append(
                TableMetadata(
                    str(name),
                    str(_value(row, "table_schema", schema)),
                    str(_value(row, "table_catalog", self.catalog))
                    if _value(row, "table_catalog", self.catalog) is not None
                    else None,
                    str(_value(row, "table_type", "table")).casefold(),
                )
            )
        return result

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        sql = self.column_sql_template.format(
            schema=_literal(schema),
            table=_literal(table),
            catalog=_literal(self.catalog or ""),
        )
        rows = self._read(sql).rows
        columns = []
        catalog: str | None = self.catalog
        for row in rows:
            catalog_value = _value(row, "table_catalog", catalog)
            if catalog_value is not None:
                catalog = str(catalog_value)
            columns.append(
                ColumnMetadata(
                    name=str(_value(row, "column_name")),
                    data_type=str(_value(row, "data_type", "UNKNOWN")),
                    nullable=_nullable(_value(row, "is_nullable", True)),
                    ordinal_position=int(_value(row, "ordinal_position"))
                    if _value(row, "ordinal_position") is not None
                    else None,
                    default=str(_value(row, "column_default"))
                    if _value(row, "column_default") is not None
                    else None,
                )
            )
        return TableMetadata(table, schema, catalog, columns=tuple(columns))

    def get_ddl(self, schema: str, table: str) -> str:
        metadata = self.describe_table(schema, table)
        if not metadata.columns:
            raise KeyError(f"{self.platform} object not found: {schema}.{table}")
        definitions = []
        for column in metadata.columns:
            nullable = "" if column.nullable else " NOT NULL"
            default = f" DEFAULT {column.default}" if column.default else ""
            definitions.append(f"{column.name} {column.data_type}{default}{nullable}")
        return f"CREATE TABLE {schema}.{table} (" + ", ".join(definitions) + ")"

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            result = self._read(self.explain_prefix + sql)
            return DryRunResult(True, metadata={"plan": list(result.rows)})
        except Exception as exc:
            return DryRunResult(
                False,
                warnings=(f"{self.platform} EXPLAIN failed",),
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        return self._read(sql)


class PostgreSQLConnector(InformationSchemaConnector):
    platform = "postgres"
    catalog_sql = (
        "SELECT datname AS catalog_name FROM pg_database "
        "WHERE datallowconn AND NOT datistemplate ORDER BY datname"
    )
    schema_sql = (
        "SELECT current_database() AS catalog_name, schema_name "
        "FROM information_schema.schemata ORDER BY schema_name"
    )

    def capabilities(self) -> set[ConnectorCapability]:
        return super().capabilities() | {ConnectorCapability.GET_QUERY_HISTORY}

    def query_history(self, *, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        result = self._read(
            "SELECT queryid, calls, total_exec_time, mean_exec_time, rows, query "
            "FROM pg_stat_statements ORDER BY total_exec_time DESC "
            f"LIMIT {max(1, min(int(limit), 10000))}"
        )
        return list(result.rows)


class RedshiftConnector(PostgreSQLConnector):
    platform = "redshift"
    catalog_sql = "SELECT current_database() AS catalog_name"

    def query_history(self, *, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        result = self._read(
            "SELECT query, userid, starttime, endtime, aborted, querytxt "
            "FROM stl_query ORDER BY starttime DESC "
            f"LIMIT {max(1, min(int(limit), 10000))}"
        )
        return list(result.rows)


class MySQLConnector(InformationSchemaConnector):
    platform = "mysql"
    catalog_sql = (
        "SELECT schema_name AS catalog_name FROM information_schema.schemata ORDER BY schema_name"
    )
    schema_sql = (
        "SELECT schema_name AS catalog_name, schema_name "
        "FROM information_schema.schemata ORDER BY schema_name"
    )


class SQLServerConnector(InformationSchemaConnector):
    platform = "sqlserver"
    catalog_sql = "SELECT name AS catalog_name FROM sys.databases ORDER BY name"
    schema_sql = (
        "SELECT DB_NAME() AS catalog_name, schema_name(schema_id) AS schema_name "
        "FROM sys.schemas ORDER BY schema_name"
    )


class OracleConnector(InformationSchemaConnector):
    platform = "oracle"
    catalog_sql = "SELECT SYS_CONTEXT('USERENV', 'DB_NAME') AS catalog_name FROM dual"
    schema_sql = (
        "SELECT SYS_CONTEXT('USERENV', 'DB_NAME') AS catalog_name, username AS schema_name "
        "FROM all_users ORDER BY username"
    )
    table_sql_template = (
        "SELECT SYS_CONTEXT('USERENV', 'DB_NAME') AS table_catalog, owner AS table_schema, "
        "table_name, 'TABLE' AS table_type FROM all_tables "
        "WHERE owner = UPPER({schema}) ORDER BY table_name"
    )
    column_sql_template = (
        "SELECT SYS_CONTEXT('USERENV', 'DB_NAME') AS table_catalog, owner AS table_schema, "
        "table_name, column_name, data_type, nullable AS is_nullable, column_id AS ordinal_position, "
        "data_default AS column_default FROM all_tab_columns "
        "WHERE owner = UPPER({schema}) AND table_name = UPPER({table}) ORDER BY column_id"
    )

    def get_ddl(self, schema: str, table: str) -> str:
        result = self._read(
            "SELECT DBMS_METADATA.GET_DDL('TABLE', "
            + _literal(table.upper())
            + ", "
            + _literal(schema.upper())
            + ") AS ddl FROM dual"
        )
        if not result.rows:
            raise KeyError(f"Oracle object not found: {schema}.{table}")
        return str(_value(result.rows[0], "ddl"))

    def capabilities(self) -> set[ConnectorCapability]:
        return super().capabilities() | {ConnectorCapability.GET_ROLE_METADATA}

    def role_metadata(self, **_: Any) -> dict[str, Any]:
        roles = self._read(
            "SELECT grantee, granted_role, admin_option, default_role "
            "FROM dba_role_privs ORDER BY grantee, granted_role"
        )
        grants = self._read(
            "SELECT grantee, owner, table_name, privilege, grantable "
            "FROM dba_tab_privs ORDER BY grantee, owner, table_name"
        )
        return {"roles": list(roles.rows), "object_grants": list(grants.rows)}


class ClickHouseConnector(InformationSchemaConnector):
    platform = "clickhouse"
    catalog_sql = "SELECT name AS catalog_name FROM system.databases ORDER BY name"
    schema_sql = "SELECT name AS catalog_name, name AS schema_name FROM system.databases ORDER BY name"
    table_sql_template = (
        "SELECT database AS table_catalog, database AS table_schema, name AS table_name, "
        "engine AS table_type FROM system.tables WHERE database = {schema} ORDER BY name"
    )
    column_sql_template = (
        "SELECT database AS table_catalog, database AS table_schema, table AS table_name, "
        "name AS column_name, type AS data_type, if(default_kind = '', 'YES', 'NO') AS is_nullable, "
        "position AS ordinal_position, default_expression AS column_default "
        "FROM system.columns WHERE database = {schema} AND table = {table} ORDER BY position"
    )

    def capabilities(self) -> set[ConnectorCapability]:
        return super().capabilities() | {ConnectorCapability.GET_QUERY_HISTORY}

    def query_history(self, *, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        result = self._read(
            "SELECT query_id, user, query_duration_ms, read_rows, read_bytes, result_rows, query "
            "FROM system.query_log WHERE type = 'QueryFinish' ORDER BY event_time DESC "
            f"LIMIT {max(1, min(int(limit), 10000))}"
        )
        return list(result.rows)


class TrinoConnector(InformationSchemaConnector):
    platform = "trino"

    def __init__(self, connection: Any, *, catalog: str) -> None:
        super().__init__(connection, catalog=catalog)

    @property
    def catalog_sql(self) -> str:
        return "SHOW CATALOGS"

    @property
    def schema_sql(self) -> str:
        return f"SHOW SCHEMAS FROM {self.catalog}"

    def list_schemas(self) -> list[SchemaMetadata]:
        rows = self._read(self.schema_sql).rows
        result = []
        for row in rows:
            value = next(iter(row.values())) if row else None
            if value is not None:
                result.append(SchemaMetadata(str(value), self.catalog))
        return result

    def list_tables(self, schema: str) -> list[TableMetadata]:
        rows = self._read(f"SHOW TABLES FROM {self.catalog}.{schema}").rows
        result = []
        for row in rows:
            value = next(iter(row.values())) if row else None
            if value is not None:
                result.append(TableMetadata(str(value), schema, self.catalog))
        return result

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        rows = self._read(f"DESCRIBE {self.catalog}.{schema}.{table}").rows
        columns = []
        for index, row in enumerate(rows, 1):
            values = list(row.values())
            if not values:
                continue
            columns.append(
                ColumnMetadata(
                    str(values[0]),
                    str(values[1]) if len(values) > 1 else "UNKNOWN",
                    True,
                    index,
                )
            )
        return TableMetadata(table, schema, self.catalog, columns=tuple(columns))


