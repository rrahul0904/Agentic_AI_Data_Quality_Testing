# Connectors

`DataPlatformConnector` is a typed, read-only default contract. Every adapter exposes discovery, table description, dry-run, and read execution only where supported. Connector code never registers writes; a production mutation must instead be exposed as an explicit `ToolDefinition` and invoked through `ToolRegistry`.

Snowflake reads account context from `ADE_SNOWFLAKE_*` variables and supports metadata, DDL retrieval, read queries, and `EXPLAIN`. Databricks reads `ADE_DATABRICKS_*` configuration and supports Unity Catalog metadata, read queries, and `EXPLAIN`. BigQuery reads `ADE_BIGQUERY_PROJECT`, performs dry runs, and returns estimated bytes and an optional cost estimate.

The SDK/client is injected by the host application. Unit tests use mocks; no live cloud account has been exercised by this repository.
