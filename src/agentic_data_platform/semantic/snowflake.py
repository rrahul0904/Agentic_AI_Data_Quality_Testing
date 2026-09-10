"""Snowflake semantic-view discovery and synchronization."""

from __future__ import annotations

from typing import Any

from agentic_data_platform.connectors._common import identifier
from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.semantic.registry import SemanticRegistry


def _qualified(value: str) -> str:
    parts = [part.strip() for part in str(value).split(".") if part.strip()]
    if not parts:
        raise ValueError("identifier is required")
    return ".".join(identifier(part) for part in parts)


class SnowflakeSemanticAdapter:
    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("SnowflakeSemanticAdapter requires SnowflakeConnector")
        self.connector = connector

    def inventory(
        self,
        *,
        database: str | None = None,
        schema: str | None = None,
        account: bool = False,
    ) -> list[dict[str, Any]]:
        sql = "SHOW SEMANTIC VIEWS"
        if account:
            sql += " IN ACCOUNT"
        elif schema:
            target = f"{database}.{schema}" if database else schema
            sql += f" IN SCHEMA {_qualified(target)}"
        elif database:
            sql += f" IN DATABASE {identifier(database)}"
        rows = self.connector.execute_read(sql).rows
        return [dict(row) for row in rows]

    def describe(self, name: str) -> list[dict[str, Any]]:
        rows = self.connector.execute_read(f"DESC SEMANTIC VIEW {_qualified(name)}").rows
        return [dict(row) for row in rows]

    def sync(
        self,
        registry: SemanticRegistry,
        *,
        database: str | None = None,
        schema: str | None = None,
        account: bool = False,
    ) -> dict[str, Any]:
        synced = []
        failed = []
        for row in self.inventory(database=database, schema=schema, account=account):
            normalized = {str(k).casefold(): v for k, v in row.items()}
            name = str(normalized.get("name") or "")
            db = str(normalized.get("database_name") or database or "")
            sch = str(normalized.get("schema_name") or schema or "")
            qualified = ".".join(item for item in (db, sch, name) if item)
            try:
                synced.append(
                    registry.ingest_describe_rows(
                        qualified or name,
                        self.describe(qualified or name),
                    )
                )
            except Exception as exc:
                failed.append({
                    "name": qualified or name,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return {
            "status": "FAIL" if failed else "PASS",
            "synced": len(synced),
            "failed": failed,
            "resources": [item["resource_id"] for item in synced],
        }
