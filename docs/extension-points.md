# Platform Extension Points

The domain layer is deliberately independent of any warehouse SDK, orchestration framework, or LLM vendor.

## Snowflake
Implement a `DataPlatformConnector` plus governed tools for metadata reads, SQL dry-runs and approved execution. Keep Snowflake SDK details behind the connector boundary.

## Databricks
Implement a connector for Unity Catalog discovery, SQL Warehouse dry-runs/execution and Jobs/Delta metadata. PySpark execution belongs behind a separate governed tool because its risk profile differs from SQL operations.

## BigQuery
Implement metadata discovery via INFORMATION_SCHEMA and a dry-run tool that returns bytes processed and syntax validation. Approved mutations must use the same `ToolRegistry` policy boundary.

## dbt
The local adapter only reads artifacts and constructs commands. Future `compile`, `test`, `run`, or `build` execution must be registered as governed tools.

## Adding a migration pair
1. Keep `MigrationSpec` platform-neutral.
2. Add a deterministic translator for the pair.
3. Validate generated SQL with the SQL layer.
4. Add fixtures and unsafe edge cases.
5. Add reconciliation rules before execution.

## PostgreSQL persistence
Implement `ControlPlaneRepository` with transactional writes and durable evidence. SQLite is the executable first implementation, not a hard dependency of the domain.
