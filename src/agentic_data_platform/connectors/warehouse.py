"""Common read-only warehouse adapter facade.

Concrete connectors remain separate; this facade gives discovery, health and
future FinOps code one stable contract without granting mutation access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agentic_data_platform.connectors.base import DataPlatformConnector


class WarehouseAdapter(ABC):
    platform: str

    @abstractmethod
    def connect(self) -> "WarehouseAdapter": ...

    @abstractmethod
    def ping(self) -> bool: ...

    @abstractmethod
    def databases(self) -> list[str]: ...

    @abstractmethod
    def schemas(self, database: str | None = None) -> list[Any]: ...

    @abstractmethod
    def tables(self, schema: str, database: str | None = None) -> list[Any]: ...

    @abstractmethod
    def columns(self, schema: str, table: str, database: str | None = None) -> list[Any]: ...

    @abstractmethod
    def query(self, sql: str) -> Any: ...

    def explain(self, sql: str) -> Any:
        return self.query(f"EXPLAIN {sql}")

    def query_history(self, **_: Any) -> list[Any]:
        return []

    def usage(self, **_: Any) -> dict[str, Any]:
        return {"status": "SKIP", "reason": f"{self.platform} usage history is not configured"}

    def cost(self, **_: Any) -> dict[str, Any]:
        return {"status": "SKIP", "reason": f"{self.platform} cost data is not configured"}


class ConnectorWarehouseAdapter(WarehouseAdapter):
    def __init__(self, connector: DataPlatformConnector, database: str | None = None) -> None:
        self.connector = connector
        self.platform = connector.platform
        self.database = database

    def connect(self) -> "ConnectorWarehouseAdapter":
        return self

    def ping(self) -> bool:
        try:
            result = self.connector.dry_run_sql("SELECT 1")
            return result.valid
        except Exception:
            return False

    def databases(self) -> list[str]:
        return self.connector.list_catalogs()

    def schemas(self, database: str | None = None) -> list[Any]:
        return self.connector.list_schemas()

    def tables(self, schema: str, database: str | None = None) -> list[Any]:
        return self.connector.list_tables(schema)

    def columns(self, schema: str, table: str, database: str | None = None) -> list[Any]:
        return list(self.connector.describe_table(schema, table).columns)

    def query(self, sql: str) -> Any:
        return self.connector.execute_read(sql)
