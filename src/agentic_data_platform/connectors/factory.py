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
    config = dict(args.get("config") or {})

    if platform == "duckdb":
        try:
            import duckdb
        except ImportError as exc:
            raise ExternalConnectionUnavailable("DuckDB driver is not installed") from exc
        database = str(args.get("database") or config.get("database") or ":memory:")
        return DuckDBConnector(duckdb.connect(database=database))

    if platform == "sqlite":
        import sqlite3

        database = str(args.get("database") or config.get("database") or os.getenv("ADE_SQLITE_DATABASE") or ":memory:")
        return SQLiteConnector(sqlite3.connect(database))

    if platform in {"postgres", "postgresql"}:
        dsn = config.get("dsn") or os.getenv("ADE_POSTGRES_DSN")
        if not dsn:
            raise ExternalConnectionUnavailable("PostgreSQL DSN is not configured")
        try:
            import psycopg
        except ImportError as exc:
            raise ExternalConnectionUnavailable("psycopg is not installed") from exc
        return PostgreSQLConnector(psycopg.connect(dsn))

    if platform == "redshift":
        dsn = config.get("dsn") or os.getenv("ADE_REDSHIFT_DSN")
        if not dsn:
            raise ExternalConnectionUnavailable("Redshift DSN is not configured")
        try:
            import psycopg
        except ImportError as exc:
            raise ExternalConnectionUnavailable("psycopg is not installed") from exc
        return RedshiftConnector(psycopg.connect(dsn))

    if platform == "mysql":
        host = config.get("host") or os.getenv("ADE_MYSQL_HOST")
        user = config.get("user") or os.getenv("ADE_MYSQL_USER")
        password = config.get("password") or os.getenv("ADE_MYSQL_PASSWORD")
        database = config.get("database") or os.getenv("ADE_MYSQL_DATABASE")
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
        connection_string = config.get("connection_string") or os.getenv("ADE_SQLSERVER_CONNECTION_STRING")
        if not connection_string:
            raise ExternalConnectionUnavailable("SQL Server connection string is not configured")
        try:
            import pyodbc
        except ImportError as exc:
            raise ExternalConnectionUnavailable("pyodbc is not installed") from exc
        return SQLServerConnector(pyodbc.connect(connection_string))

    if platform == "oracle":
        user = config.get("user") or os.getenv("ADE_ORACLE_USER")
        password = config.get("password") or os.getenv("ADE_ORACLE_PASSWORD")
        dsn = config.get("dsn") or os.getenv("ADE_ORACLE_DSN")
        if not all((user, password, dsn)):
            raise ExternalConnectionUnavailable("Oracle credentials are not configured")
        try:
            import oracledb
        except ImportError as exc:
            raise ExternalConnectionUnavailable("oracledb is not installed") from exc
        return OracleConnector(oracledb.connect(user=user, password=password, dsn=dsn))

    if platform == "clickhouse":
        host = config.get("host") or os.getenv("ADE_CLICKHOUSE_HOST")
        user = config.get("user") or os.getenv("ADE_CLICKHOUSE_USER")
        password = config.get("password") or os.getenv("ADE_CLICKHOUSE_PASSWORD")
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
        host = config.get("host") or os.getenv("ADE_TRINO_HOST")
        user = config.get("user") or os.getenv("ADE_TRINO_USER")
        catalog = config.get("catalog") or os.getenv("ADE_TRINO_CATALOG")
        if not all((host, user, catalog)):
            raise ExternalConnectionUnavailable("Trino host/user/catalog are not configured")
        try:
            import trino
        except ImportError as exc:
            raise ExternalConnectionUnavailable("trino client is not installed") from exc
        connection = trino.dbapi.connect(
            host=host,
            port=int(config.get("port") or os.getenv("ADE_TRINO_PORT", "8080")),
            user=user,
            catalog=catalog,
            schema=config.get("schema") or os.getenv("ADE_TRINO_SCHEMA"),
            http_scheme=config.get("http_scheme") or os.getenv("ADE_TRINO_HTTP_SCHEME", "https"),
        )
        return TrinoConnector(connection, catalog=catalog)

    if platform == "snowflake":
        account = config.get("account") or os.getenv("ADE_SNOWFLAKE_ACCOUNT")
        user = config.get("user") or os.getenv("ADE_SNOWFLAKE_USER")
        password = config.get("password") or os.getenv("ADE_SNOWFLAKE_PASSWORD")
        if not all((account, user, password)):
            raise ExternalConnectionUnavailable("Snowflake credentials are not configured")
        try:
            import snowflake.connector
        except ImportError as exc:
            raise ExternalConnectionUnavailable("Snowflake connector is not installed") from exc
        sf_config = SnowflakeConfig(
            account=account,
            user=user,
            database=config.get("database") or os.getenv("ADE_SNOWFLAKE_DATABASE"),
            schema=config.get("schema") or os.getenv("ADE_SNOWFLAKE_SCHEMA"),
            warehouse=config.get("warehouse") or os.getenv("ADE_SNOWFLAKE_WAREHOUSE"),
            role=config.get("role") or os.getenv("ADE_SNOWFLAKE_ROLE"),
        )
        connection = snowflake.connector.connect(
            account=sf_config.account,
            user=sf_config.user,
            password=password,
            database=sf_config.database,
            schema=sf_config.schema,
            warehouse=sf_config.warehouse,
            role=sf_config.role,
        )
        return SnowflakeConnector(connection, sf_config)

    if platform == "bigquery":
        project = config.get("project") or os.getenv("ADE_BIGQUERY_PROJECT")
        if not project:
            raise ExternalConnectionUnavailable("BigQuery project is not configured")
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise ExternalConnectionUnavailable("BigQuery driver is not installed") from exc
        config = BigQueryConfig(project)
        return BigQueryConnector(bigquery.Client(project=project), config)

    if platform == "databricks":
        db_config = DatabricksConfig(
            host=config.get("host") or os.getenv("ADE_DATABRICKS_HOST"),
            token=config.get("token") or os.getenv("ADE_DATABRICKS_TOKEN"),
            http_path=config.get("http_path") or os.getenv("ADE_DATABRICKS_HTTP_PATH"),
            catalog=config.get("catalog") or os.getenv("ADE_DATABRICKS_CATALOG"),
        )
        if not (db_config.host and db_config.token and db_config.http_path):
            raise ExternalConnectionUnavailable("Databricks credentials are not configured")
        try:
            from databricks import sql as databricks_sql
        except ImportError as exc:
            raise ExternalConnectionUnavailable("Databricks SQL connector is not installed") from exc
        connection = databricks_sql.connect(
            server_hostname=db_config.host.replace("https://", "").rstrip("/"),
            http_path=db_config.http_path,
            access_token=db_config.token,
        )
        return DatabricksConnector(connection, db_config)

    raise ExternalConnectionUnavailable(
        f"No configured runtime connector for {platform}; install/implement the warehouse driver before live execution"
    )
