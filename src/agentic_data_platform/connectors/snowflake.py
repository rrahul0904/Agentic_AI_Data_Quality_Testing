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
        return {
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
            ConnectorCapability.QUERY_WRITE,
            ConnectorCapability.GET_DDL,
            ConnectorCapability.GET_QUERY_HISTORY,
            ConnectorCapability.GET_COST_METADATA,
            ConnectorCapability.GET_ROLE_METADATA,
        }

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

    def execute_governed_mutation(self, sql: str) -> QueryResult:
        """Execute a mutation only when called by the governed mutation layer.

        The base connector's execute()/execute_read() methods remain read-only.
        Callers must route writes through ToolRegistry and the Snowflake mutation
        planner so approval, environment policy, fingerprint binding, and
        post-execution verification are enforced before this method is reached.
        """
        raw = execute(self._executor, sql)
        try:
            return query_result(raw)
        except Exception:
            return QueryResult(
                (),
                (),
                getattr(raw, "sfqid", None),
                {"statement_executed": True},
            )

    def query_history(self, *, days: int = 7, limit: int = 1000, **_: Any) -> list[dict[str, Any]]:
        days = max(1, min(int(days), 365))
        limit = max(1, min(int(limit), 10000))
        sql = (
            "SELECT query_id, query_text, database_name, schema_name, query_type, "
            "warehouse_name, warehouse_size, user_name, role_name, execution_status, "
            "error_code, error_message, total_elapsed_time, execution_time, queued_overload_time, "
            "queued_provisioning_time, bytes_scanned, bytes_spilled_to_local_storage, "
            "bytes_spilled_to_remote_storage, rows_produced, start_time, end_time "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
            f"WHERE start_time >= DATEADD(day, -{days}, CURRENT_TIMESTAMP()) "
            "ORDER BY start_time DESC "
            f"LIMIT {limit}"
        )
        return list(self._read(sql).rows)

    def warehouse_usage(self, *, days: int = 7, **_: Any) -> dict[str, Any]:
        days = max(1, min(int(days), 365))
        metering = self._read(
            "SELECT warehouse_name, SUM(credits_used) AS credits_used, "
            "SUM(credits_used_compute) AS compute_credits, "
            "SUM(credits_used_cloud_services) AS cloud_services_credits, "
            "MIN(start_time) AS first_seen, MAX(end_time) AS last_seen "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY "
            f"WHERE start_time >= DATEADD(day, -{days}, CURRENT_TIMESTAMP()) "
            "GROUP BY warehouse_name ORDER BY credits_used DESC"
        )
        load = self._read(
            "SELECT warehouse_name, AVG(avg_running) AS avg_running, "
            "MAX(avg_running) AS peak_running, AVG(avg_queued_load) AS avg_queued_load, "
            "MAX(avg_queued_load) AS peak_queued_load, AVG(avg_queued_provisioning) AS avg_queued_provisioning "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY "
            f"WHERE start_time >= DATEADD(day, -{days}, CURRENT_TIMESTAMP()) "
            "GROUP BY warehouse_name"
        )
        warehouses = self._read("SHOW WAREHOUSES")
        return {
            "days": days,
            "metering": list(metering.rows),
            "load": list(load.rows),
            "warehouses": list(warehouses.rows),
        }

    def cost_usage(self, *, days: int = 7, credit_price_usd: float | None = None, **_: Any) -> dict[str, Any]:
        usage = self.warehouse_usage(days=days)
        total_credits = sum(float(row.get("credits_used") or row.get("CREDITS_USED") or 0) for row in usage["metering"])
        return {
            "days": days,
            "credits_used": total_credits,
            "credit_price_usd": credit_price_usd,
            "estimated_cost_usd": total_credits * credit_price_usd if credit_price_usd is not None else None,
            "by_warehouse": usage["metering"],
        }

    def role_metadata(self, **_: Any) -> dict[str, Any]:
        grants_to_roles = self._read("SHOW GRANTS TO ROLE")
        grants_to_users = self._read("SHOW GRANTS TO USER")
        roles = self._read("SHOW ROLES")
        return {
            "roles": list(roles.rows),
            "role_grants": list(grants_to_roles.rows),
            "user_grants": list(grants_to_users.rows),
        }
