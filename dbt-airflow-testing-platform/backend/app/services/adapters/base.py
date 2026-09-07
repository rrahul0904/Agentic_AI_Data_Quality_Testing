"""Adapter SDK (Master Prompt §14/§15). Data platforms and pipeline
orchestrators are integrations, not the architecture -- the Quality Rule
Engine and orchestrator depend on these interfaces, never on a specific
warehouse or scheduler.

Only DuckDBAdapter is fully implemented and live-tested in this phase (see
duckdb_adapter.py). Snowflake/BigQuery/Redshift/Databricks are declared here
as the contract every future adapter must satisfy, not implemented -- do not
claim otherwise (see docs/CURRENT_STATE.md and the plan's capability
matrix).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ColumnSchema:
    name: str
    data_type: str
    nullable: bool = True


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]

    def scalar(self):
        """Convenience for single-value aggregate/count queries."""
        return self.rows[0][0] if self.rows and self.rows[0] else None

    def as_dicts(self) -> list[dict]:
        return [dict(zip(self.columns, row)) for row in self.rows]


@dataclass
class DryRunEstimate:
    estimated_bytes: int | None = None
    estimated_rows: int | None = None
    supported: bool = False


class DataPlatformAdapter(ABC):
    """One adapter per warehouse/lakehouse. Every quality-rule execution and
    reconciliation goes through this interface, never a raw platform SDK
    call scattered through business logic."""

    dialect: str  # sqlglot dialect name, e.g. "duckdb", "snowflake"

    @abstractmethod
    def test_connection(self) -> bool: ...

    @abstractmethod
    def get_row_count(self, table: str, predicate: str | None = None) -> int: ...

    @abstractmethod
    def get_schema(self, table: str) -> list[ColumnSchema]: ...

    @abstractmethod
    def execute_query(self, sql: str) -> QueryResult:
        """Executes read-only SQL and returns a (typically small) result set.
        Callers are responsible for keeping results small (Master Prompt
        §23, "data locality") -- this is not a bulk-extract API."""
        ...

    def estimate_query_cost(self, sql: str) -> DryRunEstimate:
        """Optional: adapters that support dry-run cost estimation (BigQuery,
        Snowflake EXPLAIN) override this. Default: unsupported."""
        return DryRunEstimate(supported=False)


@dataclass
class PipelineRunOutcome:
    run_id: str | None
    state: str
    detail: dict = field(default_factory=dict)


class PipelineAdapter(ABC):
    """One adapter per orchestrator (Airflow, dbt Core, dbt Cloud, and
    later MWAA/Composer/Astronomer/Dagster/Prefect). Wraps the existing
    concrete implementations (airflow_client.py, dbt_runner.py,
    dbt_cloud_client.py) rather than replacing them."""

    @abstractmethod
    def test_connection(self) -> bool: ...

    @abstractmethod
    def trigger(self, ref: str, params: dict | None = None) -> PipelineRunOutcome: ...

    @abstractmethod
    def get_run(self, run_id: str) -> PipelineRunOutcome: ...
