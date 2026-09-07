"""Create configured read-only connectors without exposing credentials."""

from __future__ import annotations

import os
from typing import Any

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.bigquery import BigQueryConfig, BigQueryConnector
from agentic_data_platform.connectors.databricks import DatabricksConfig, DatabricksConnector
from agentic_data_platform.connectors.duckdb import DuckDBConnector
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
