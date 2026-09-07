from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import DryRunResult, QueryResult, SchemaMetadata, TableMetadata
from agentic_data_platform.sql.safety import classify_mutation


class DataPlatformConnector(ABC):
    """Read-only connector contract. Write support is deliberately absent by default."""

    platform: str

    @abstractmethod
    def capabilities(self) -> set[ConnectorCapability]: ...

    @abstractmethod
    def list_schemas(self) -> list[SchemaMetadata]: ...

    @abstractmethod
    def list_tables(self, schema: str) -> list[TableMetadata]: ...

    @abstractmethod
    def describe_table(self, schema: str, table: str) -> TableMetadata: ...

    @abstractmethod
    def dry_run_sql(self, sql: str) -> DryRunResult: ...

    @abstractmethod
    def execute_read(self, sql: str) -> QueryResult: ...

    def list_catalogs(self) -> list[str]:
        raise NotImplementedError(f"{self.platform} does not expose catalog discovery")

    def get_ddl(self, schema: str, table: str) -> str:
        raise NotImplementedError(f"{self.platform} does not expose DDL retrieval")

    # Wave 1 compatibility. It intentionally remains a restricted interface.
    def introspect(self, scope: str) -> dict[str, Any]:
        return {"scope": scope, "schemas": [item.name for item in self.list_schemas()]}

    def dry_run(self, statement: str) -> dict[str, Any]:
        return self.dry_run_sql(statement).__dict__

    def execute(self, statement: str) -> dict[str, Any]:
        return self.execute_read(statement).__dict__

    @staticmethod
    def require_read_only(sql: str) -> None:
        if classify_mutation(sql) != "read":
            raise PermissionError("connector permits read-only SQL only; mutations require a registered governed tool")
