"""Create configured read-only connectors without exposing credentials."""

from __future__ import annotations

import os
from typing import Any

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.bigquery import BigQueryConfig, BigQueryConnector
from agentic_data_platform.connectors.databricks import DatabricksConfig, DatabricksConnector
from agentic_data_platform.connectors.duckdb import DuckDBConnector
from agentic_data_platform.connectors.information_schema import (
    MySQLConnector,
    PostgreSQLConnector,
    RedshiftConnector,
    SQLServerConnector,
)
from agentic_data_platform.connectors.oracle import OracleConnector
from agentic_data_platform.connectors.sqlite import SQLiteConnector
from agentic_data_platform.connectors.clickhouse import ClickHouseConnector
from agentic_data_platform.connectors.trino import TrinoConnector
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector


class ExternalConnectionUnavailable(RuntimeError):
    pass


def connector_from_args(args: dict[str, Any]) -> DataPlatformConnector:
    injected = args.get("_connector")
    if isinstance(injected, DataPlatformConnector):
        return injected

    platform = str(args.get("platform") or "duckdb").casefold()

    if platform == "duckdb":
        try:
            import duckdb
        except ImportError as exc:
            raise ExternalConnectionUnavailable("DuckDB driver is not installed") from exc
        database = str(args.get("database") or ":memory:")
        return DuckDBConnector(duckdb.connect(database=database))

    if platform == "sqlite":
        import sqlite3

        database = str(args.get("database") or os.getenv("ADE_SQLITE_DATABASE") or ":memory:")
        return SQLiteConnector(sqlite3.connect(database))

    if platform in {"postgres", "postgresql"}:
        dsn = os.getenv("ADE_POSTGRES_DSN")
        if not dsn:
            raise ExternalConnectionUnavailable("PostgreSQL DSN is not configured")
        try:
            import psycopg
        except ImportError as exc:
            raise ExternalConnectionUnavailable("psycopg is not installed") from exc
        return PostgreSQLConnector(psycopg.connect(dsn))

    if platform == "redshift":
        dsn = os.getenv("ADE_REDSHIFT_DSN")
        if not dsn:
            raise ExternalConnectionUnavailable("Redshift DSN is not configured")
        try:
            import psycopg
        except ImportError as exc:
            raise ExternalConnectionUnavailable("psycopg is not installed") from exc
        return RedshiftConnector(psycopg.connect(dsn))

    if platform == "mysql":
        host = os.getenv("ADE_MYSQL_HOST")
        user = os.getenv("ADE_MYSQL_USER")
        password = os.getenv("ADE_MYSQL_PASSWORD")
        database = os.getenv("ADE_MYSQL_DATABASE")
        if not all((host, user, password, database)):
            raise ExternalConnectionUnavailable("MySQL credentials are not configured")
        try:
            import pymysql
        except ImportError as exc:
            raise ExternalConnectionUnavailable("PyMySQL is not installed") from exc
        return MySQLConnector(
            pymysql.connect(host=host, user=user, password=password, database=database)
        )

    if platform in {"sqlserver", "mssql", "fabric"}:
        connection_string = os.getenv("ADE_SQLSERVER_CONNECTION_STRING")
        if not connection_string:
            raise ExternalConnectionUnavailable("SQL Server connection string is not configured")
        try:
            import pyodbc
        except ImportError as exc:
            raise ExternalConnectionUnavailable("pyodbc is not installed") from exc
        return SQLServerConnector(pyodbc.connect(connection_string))

    if platform == "oracle":
        user = os.getenv("ADE_ORACLE_USER")
        password = os.getenv("ADE_ORACLE_PASSWORD")
        dsn = os.getenv("ADE_ORACLE_DSN")
        if not all((user, password, dsn)):
            raise ExternalConnectionUnavailable("Oracle credentials are not configured")
        try:
            import oracledb
        except ImportError as exc:
            raise ExternalConnectionUnavailable("oracledb is not installed") from exc
        return OracleConnector(oracledb.connect(user=user, password=password, dsn=dsn))

    if platform == "clickhouse":
        host = os.getenv("ADE_CLICKHOUSE_HOST")
        user = os.getenv("ADE_CLICKHOUSE_USER")
        password = os.getenv("ADE_CLICKHOUSE_PASSWORD")
        if not host:
            raise ExternalConnectionUnavailable("ClickHouse host is not configured")
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise ExternalConnectionUnavailable("clickhouse-connect is not installed") from exc
        client = clickhouse_connect.get_client(host=host, username=user or "default", password=password or "")

        def clickhouse_executor(sql: str) -> dict[str, Any]:
            result = client.query(sql)
            return {
                "columns": tuple(result.column_names),
                "rows": tuple(dict(zip(result.column_names, row, strict=False)) for row in result.result_rows),
            }

        return ClickHouseConnector(clickhouse_executor)

    if platform == "trino":
        host = os.getenv("ADE_TRINO_HOST")
        user = os.getenv("ADE_TRINO_USER")
        catalog = os.getenv("ADE_TRINO_CATALOG")
        if not all((host, user, catalog)):
            raise ExternalConnectionUnavailable("Trino host/user/catalog are not configured")
        try:
            import trino
        except ImportError as exc:
            raise ExternalConnectionUnavailable("trino client is not installed") from exc
        connection = trino.dbapi.connect(
            host=host,
            port=int(os.getenv("ADE_TRINO_PORT", "8080")),
            user=user,
            catalog=catalog,
            schema=os.getenv("ADE_TRINO_SCHEMA"),
            http_scheme=os.getenv("ADE_TRINO_HTTP_SCHEME", "https"),
        )
        return TrinoConnector(connection, catalog=catalog)

    if platform == "snowflake":
        required = ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD")
        if not all(os.getenv(name) for name in required):
            raise ExternalConnectionUnavailable("Snowflake credentials are not configured")
        try:
            import snowflake.connector
        except ImportError as exc:
            raise ExternalConnectionUnavailable("Snowflake connector is not installed") from exc
        config = SnowflakeConfig.from_env()
        connection = snowflake.connector.connect(
            account=config.account,
            user=config.user,
            password=os.getenv("ADE_SNOWFLAKE_PASSWORD"),
            database=config.database,
            schema=config.schema,
            warehouse=config.warehouse,
            role=config.role,
        )
        return SnowflakeConnector(connection, config)

    if platform == "bigquery":
        project = os.getenv("ADE_BIGQUERY_PROJECT")
        if not project:
            raise ExternalConnectionUnavailable("BigQuery project is not configured")
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise ExternalConnectionUnavailable("BigQuery driver is not installed") from exc
        config = BigQueryConfig(project)
        return BigQueryConnector(bigquery.Client(project=project), config)

    if platform == "databricks":
        config = DatabricksConfig.from_env()
        if not (config.host and config.token and config.http_path):
            raise ExternalConnectionUnavailable("Databricks credentials are not configured")
        try:
            from databricks import sql as databricks_sql
        except ImportError as exc:
            raise ExternalConnectionUnavailable("Databricks SQL connector is not installed") from exc
        connection = databricks_sql.connect(
            server_hostname=config.host.replace("https://", "").rstrip("/"),
            http_path=config.http_path,
            access_token=config.token,
        )
        return DatabricksConnector(connection, config)

    raise ExternalConnectionUnavailable(
        f"No configured runtime connector for {platform}; install/implement the warehouse driver before live execution"
    )
