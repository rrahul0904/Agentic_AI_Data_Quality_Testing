"""Read-only MongoDB metadata/query adapter.

MongoDB is intentionally exposed through a JSON read contract rather than pretending
that MongoDB accepts SQL. The connector never returns credentials and rejects write
stages/operators.
"""

from __future__ import annotations

import json
from typing import Any

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import (
    ColumnMetadata,
    DryRunResult,
    QueryResult,
    SchemaMetadata,
    TableMetadata,
)

_WRITE_KEYS = {
    "$out", "$merge", "$set", "$unset", "$inc", "$push", "$pull", "$rename",
    "$currentDate", "$addToSet", "$pop", "$mul", "$min", "$max",
}


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _contains_write(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in _WRITE_KEYS or _contains_write(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_write(item) for item in value)
    return False


class MongoDBConnector(DataPlatformConnector):
    platform = "mongodb"

    def __init__(self, client: Any, database: str | None = None) -> None:
        self.client = client
        self.database = database

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.LIST_CATALOGS,
            ConnectorCapability.LIST_SCHEMAS,
            ConnectorCapability.LIST_TABLES,
            ConnectorCapability.DESCRIBE_TABLE,
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
        }

    def list_catalogs(self) -> list[str]:
        return sorted(str(name) for name in self.client.list_database_names())

    def list_schemas(self) -> list[SchemaMetadata]:
        return [SchemaMetadata(name) for name in self.list_catalogs()]

    def list_tables(self, schema: str) -> list[TableMetadata]:
        database = self.client[schema]
        return [
            TableMetadata(str(name), schema, object_type="collection")
            for name in sorted(database.list_collection_names())
        ]

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        collection = self.client[schema][table]
        sample = list(collection.find({}, limit=100))
        observed: dict[str, set[str]] = {}
        for document in sample:
            for key, value in document.items():
                observed.setdefault(str(key), set()).add(_type_name(value))
        columns = tuple(
            ColumnMetadata(
                name,
                "|".join(sorted(types)),
                nullable="null" in types or len(sample) == 0,
                ordinal_position=index,
            )
            for index, (name, types) in enumerate(sorted(observed.items()), 1)
        )
        return TableMetadata(table, schema, object_type="collection", columns=columns)

    def _parse(self, query: str) -> dict[str, Any]:
        if query.strip().upper() == "SELECT 1":
            return {"ping": True}
        try:
            payload = json.loads(query)
        except json.JSONDecodeError as exc:
            raise ValueError("MongoDB read queries must be JSON objects") from exc
        if not isinstance(payload, dict):
            raise ValueError("MongoDB read query must be a JSON object")
        if _contains_write(payload):
            raise PermissionError("MongoDB connector blocks write operators/stages")
        collection = payload.get("collection")
        if not isinstance(collection, str) or not collection.strip():
            raise ValueError("MongoDB read query requires collection")
        operation = str(payload.get("operation") or "find").casefold()
        if operation not in {"find", "aggregate"}:
            raise PermissionError("MongoDB connector permits only find and aggregate")
        return payload

    def dry_run_sql(self, sql: str) -> DryRunResult:
        try:
            payload = self._parse(sql)
        except (ValueError, PermissionError) as exc:
            return DryRunResult(False, warnings=(str(exc),))
        return DryRunResult(True, metadata={"platform": self.platform, "operation": payload.get("operation", "ping")})

    def execute_read(self, sql: str) -> QueryResult:
        payload = self._parse(sql)
        if payload.get("ping"):
            return QueryResult(rows=({"ok": 1},), columns=("ok",))
        database_name = str(payload.get("database") or self.database or "")
        if not database_name:
            raise ValueError("MongoDB database is not configured")
        collection = self.client[database_name][payload["collection"]]
        limit = max(1, min(int(payload.get("limit", 100)), 1000))
        if str(payload.get("operation") or "find").casefold() == "aggregate":
            pipeline = payload.get("pipeline") or []
            if not isinstance(pipeline, list) or _contains_write(pipeline):
                raise PermissionError("MongoDB aggregate pipeline must be read-only")
            rows = list(collection.aggregate(pipeline))[:limit]
        else:
            filter_doc = payload.get("filter") or {}
            projection = payload.get("projection")
            rows = list(collection.find(filter_doc, projection, limit=limit))
        normalized = tuple({str(k): v for k, v in row.items()} for row in rows)
        columns = tuple(sorted({key for row in normalized for key in row}))
        return QueryResult(rows=normalized, columns=columns, metadata={"database": database_name, "collection": payload["collection"]})
