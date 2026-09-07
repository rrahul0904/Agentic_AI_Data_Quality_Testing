from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import ColumnMetadata, DryRunResult, QueryResult, SchemaMetadata, TableMetadata


@dataclass(frozen=True)
class BigQueryConfig:
    project: str | None = None

    @classmethod
    def from_env(cls) -> "BigQueryConfig":
        return cls(os.getenv("ADE_BIGQUERY_PROJECT"))


class BigQueryConnector(DataPlatformConnector):
    platform = "bigquery"

    def __init__(self, client: Any, config: BigQueryConfig | None = None, *, cost_per_tb: Decimal = Decimal("6")) -> None:
        self._client = client
        self.config = config or BigQueryConfig.from_env()
        self.cost_per_tb = cost_per_tb

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.LIST_CATALOGS,
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
            ConnectorCapability.GET_QUERY_HISTORY,
            ConnectorCapability.GET_COST_METADATA,
        }

    def list_catalogs(self) -> list[str]:
        return [str(item.project_id) for item in self._client.list_projects()]

    def list_schemas(self) -> list[SchemaMetadata]:
        project = self.config.project
        if not project:
            raise ValueError("ADE_BIGQUERY_PROJECT is required for dataset discovery")
        return [SchemaMetadata(str(item.dataset_id), project) for item in self._client.list_datasets(project)]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        project = self.config.project
        return [TableMetadata(str(item.table_id), schema, project, str(item.table_type).lower()) for item in self._client.list_tables(f"{project}.{schema}")]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        project = self.config.project
        raw = self._client.get_table(f"{project}.{schema}.{table}")
        columns = tuple(ColumnMetadata(field.name, field.field_type, field.mode != "REQUIRED", precision=getattr(field, "precision", None), scale=getattr(field, "scale", None)) for field in raw.schema)
        return TableMetadata(table, schema, project, "view" if getattr(raw, "view_query", None) else "table", columns)

    def dry_run_sql(self, sql: str) -> DryRunResult:
        self.require_read_only(sql)
        try:
            from google.cloud import bigquery  # type: ignore[import-not-found]

            job = self._client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        except ImportError:
            job = self._client.query(sql, dry_run=True, use_query_cache=False)
        except Exception as exc:
            return DryRunResult(False, warnings=("BigQuery dry run failed",), metadata={"error": str(exc)})
        bytes_processed = getattr(job, "total_bytes_processed", None)
        cost = (Decimal(bytes_processed) / Decimal(1024**4) * self.cost_per_tb) if bytes_processed is not None else None
        return DryRunResult(True, bytes_processed, cost, metadata={"job_id": getattr(job, "job_id", None)})

    def execute_read(self, sql: str) -> QueryResult:
        self.require_read_only(sql)
        job = self._client.query(sql)
        rows = tuple(dict(row.items()) for row in job.result())
        return QueryResult(rows, tuple(rows[0]) if rows else (), getattr(job, "job_id", None), {"total_bytes_processed": getattr(job, "total_bytes_processed", None)})

    def query_history(self, *, days: int = 7, limit: int = 1000, region: str = "region-us", **_: Any) -> list[dict[str, Any]]:
        project = self.config.project
        if not project:
            raise ValueError("BigQuery project is required for query history")
        days = max(1, min(int(days), 180))
        limit = max(1, min(int(limit), 10000))
        region = region.replace(chr(96), "")
        sql = (
            f"SELECT job_id AS query_id, query AS query_text, user_email AS user_name, "
            "statement_type AS query_type, state AS execution_status, error_result, "
            "total_bytes_processed AS bytes_scanned, total_slot_ms, creation_time AS start_time, "
            "end_time "
            f"FROM \`{project}.{region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT\` "
            f"WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY) "
            "AND job_type = 'QUERY' ORDER BY creation_time DESC "
            f"LIMIT {limit}"
        )
        return list(self.execute_read(sql).rows)

    def cost_usage(self, *, days: int = 7, region: str = "region-us", **_: Any) -> dict[str, Any]:
        rows = self.query_history(days=days, limit=10000, region=region)
        total_bytes = sum(int(row.get("bytes_scanned") or 0) for row in rows)
        estimated = Decimal(total_bytes) / Decimal(1024**4) * self.cost_per_tb
        return {
            "days": days,
            "bytes_processed": total_bytes,
            "estimated_on_demand_cost_usd": str(estimated),
            "note": "On-demand scan estimate; reservations/editions may use different billing.",
        }
