"""Persistent warehouse metadata service used by search, autocomplete, lineage and governance."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.models import new_id, utc_now


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata_objects (
  object_id TEXT PRIMARY KEY,
  connection_name TEXT NOT NULL,
  warehouse TEXT NOT NULL,
  catalog TEXT,
  schema_name TEXT NOT NULL,
  object_name TEXT NOT NULL,
  object_type TEXT NOT NULL,
  owner TEXT,
  comment TEXT,
  tags_json TEXT NOT NULL,
  primary_key_json TEXT NOT NULL,
  foreign_keys_json TEXT NOT NULL,
  partitioning_json TEXT NOT NULL,
  clustering_json TEXT NOT NULL,
  refreshed_at TEXT NOT NULL,
  UNIQUE(connection_name, catalog, schema_name, object_name)
);
CREATE TABLE IF NOT EXISTS metadata_columns (
  column_id TEXT PRIMARY KEY,
  object_id TEXT NOT NULL,
  column_name TEXT NOT NULL,
  ordinal_position INTEGER,
  data_type TEXT,
  nullable INTEGER NOT NULL,
  default_value TEXT,
  comment TEXT,
  tags_json TEXT NOT NULL,
  pii_category TEXT,
  pii_confidence REAL,
  refreshed_at TEXT NOT NULL,
  UNIQUE(object_id, column_name)
);
CREATE TABLE IF NOT EXISTS metadata_refresh_runs (
  run_id TEXT PRIMARY KEY,
  connection_name TEXT NOT NULL,
  warehouse TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  schemas_seen INTEGER NOT NULL DEFAULT 0,
  objects_seen INTEGER NOT NULL DEFAULT 0,
  columns_seen INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_metadata_objects_name ON metadata_objects(object_name);
CREATE INDEX IF NOT EXISTS idx_metadata_columns_name ON metadata_columns(column_name);
CREATE INDEX IF NOT EXISTS idx_metadata_columns_pii ON metadata_columns(pii_category);
"""


class MetadataService:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def refresh(
        self,
        connection_name: str,
        connector: DataPlatformConnector,
        *,
        schemas: Iterable[str] | None = None,
        max_objects: int = 5000,
    ) -> dict[str, Any]:
        run_id = new_id("metadata_refresh")
        started = utc_now()
        self.connection.execute(
            "INSERT INTO metadata_refresh_runs VALUES (?, ?, ?, 'RUNNING', ?, NULL, 0, 0, 0, NULL)",
            (run_id, connection_name, connector.platform, started),
        )
        self.connection.commit()

        schema_count = object_count = column_count = 0
        try:
            available = connector.list_schemas()
            allowed = {item.casefold() for item in schemas} if schemas else None
            for schema_meta in available:
                if allowed and schema_meta.name.casefold() not in allowed:
                    continue
                schema_count += 1
                for table in connector.list_tables(schema_meta.name):
                    if object_count >= max_objects:
                        raise RuntimeError(f"metadata refresh exceeded max_objects={max_objects}")
                    object_count += 1
                    detail = connector.describe_table(schema_meta.name, table.name)
                    tags: list[dict[str, Any]] = []
                    if connector.supports(ConnectorCapability.GET_METADATA_TAGS):
                        try:
                            tags = list(connector.tags(schema=schema_meta.name, table=table.name))
                        except Exception:
                            tags = []

                    now = utc_now()
                    object_id = (
                        f"{connection_name}:"
                        f"{detail.catalog or table.catalog or ''}:"
                        f"{schema_meta.name}:{table.name}"
                    )
                    self.connection.execute(
                        """
                        INSERT INTO metadata_objects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(connection_name, catalog, schema_name, object_name)
                        DO UPDATE SET
                          warehouse=excluded.warehouse,
                          object_type=excluded.object_type,
                          owner=excluded.owner,
                          comment=excluded.comment,
                          tags_json=excluded.tags_json,
                          primary_key_json=excluded.primary_key_json,
                          foreign_keys_json=excluded.foreign_keys_json,
                          partitioning_json=excluded.partitioning_json,
                          clustering_json=excluded.clustering_json,
                          refreshed_at=excluded.refreshed_at
                        """,
                        (
                            object_id,
                            connection_name,
                            connector.platform,
                            detail.catalog or table.catalog,
                            schema_meta.name,
                            table.name,
                            table.object_type,
                            None,
                            detail.comment or table.comment,
                            json.dumps(tags, sort_keys=True, default=str),
                            "[]",
                            "[]",
                            "{}",
                            "{}",
                            now,
                        ),
                    )
                    for column in detail.columns:
                        column_count += 1
                        column_id = f"{object_id}:{column.name}"
                        self.connection.execute(
                            """
                            INSERT INTO metadata_columns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                            ON CONFLICT(object_id, column_name)
                            DO UPDATE SET
                              ordinal_position=excluded.ordinal_position,
                              data_type=excluded.data_type,
                              nullable=excluded.nullable,
                              default_value=excluded.default_value,
                              comment=excluded.comment,
                              tags_json=excluded.tags_json,
                              refreshed_at=excluded.refreshed_at
                            """,
                            (
                                column_id,
                                object_id,
                                column.name,
                                column.ordinal_position,
                                column.data_type,
                                int(column.nullable),
                                column.default,
                                None,
                                "[]",
                                now,
                            ),
                        )
            self.connection.execute(
                """
                UPDATE metadata_refresh_runs
                SET status='SUCCESS', completed_at=?, schemas_seen=?, objects_seen=?, columns_seen=?
                WHERE run_id=?
                """,
                (utc_now(), schema_count, object_count, column_count, run_id),
            )
            self.connection.commit()
            return {
                "run_id": run_id,
                "connection_name": connection_name,
                "warehouse": connector.platform,
                "status": "PASS",
                "schemas": schema_count,
                "objects": object_count,
                "columns": column_count,
            }
        except Exception as exc:
            self.connection.execute(
                """
                UPDATE metadata_refresh_runs
                SET status='FAILED', completed_at=?, schemas_seen=?, objects_seen=?, columns_seen=?, error=?
                WHERE run_id=?
                """,
                (
                    utc_now(),
                    schema_count,
                    object_count,
                    column_count,
                    f"{type(exc).__name__}: {exc}",
                    run_id,
                ),
            )
            self.connection.commit()
            raise

    def status(self, connection_name: str | None = None) -> dict[str, Any]:
        params: tuple[Any, ...] = ()
        where = ""
        if connection_name:
            where = " WHERE connection_name = ?"
            params = (connection_name,)
        counts = self.connection.execute(
            "SELECT COUNT(*) AS objects, COUNT(DISTINCT schema_name) AS schemas "
            f"FROM metadata_objects{where}",
            params,
        ).fetchone()
        column_sql = (
            "SELECT COUNT(*) AS columns FROM metadata_columns c "
            "JOIN metadata_objects o ON o.object_id = c.object_id"
        )
        if connection_name:
            column_sql += " WHERE o.connection_name = ?"
        column_count = self.connection.execute(column_sql, params).fetchone()["columns"]
        run = self.connection.execute(
            "SELECT * FROM metadata_refresh_runs"
            + (" WHERE connection_name = ?" if connection_name else "")
            + " ORDER BY started_at DESC LIMIT 1",
            params,
        ).fetchone()
        return {
            "connection_name": connection_name,
            "schemas": int(counts["schemas"] or 0),
            "objects": int(counts["objects"] or 0),
            "columns": int(column_count or 0),
            "last_refresh": dict(run) if run else None,
        }

    def search_assets(
        self,
        query: str,
        *,
        connection_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM metadata_objects WHERE lower(object_name) LIKE ?"
        params: list[Any] = [f"%{query.casefold()}%"]
        if connection_name:
            sql += " AND connection_name = ?"
            params.append(connection_name)
        sql += " ORDER BY schema_name, object_name LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        return [self._object(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def search_columns(
        self,
        query: str,
        *,
        connection_name: str | None = None,
        pii_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*, o.connection_name, o.warehouse, o.catalog, o.schema_name, o.object_name "
            "FROM metadata_columns c JOIN metadata_objects o ON o.object_id = c.object_id "
            "WHERE lower(c.column_name) LIKE ?"
        )
        params: list[Any] = [f"%{query.casefold()}%"]
        if connection_name:
            sql += " AND o.connection_name = ?"
            params.append(connection_name)
        if pii_only:
            sql += " AND c.pii_category IS NOT NULL"
        sql += " ORDER BY o.schema_name, o.object_name, c.ordinal_position LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        return [self._column(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def inspect(self, connection_name: str, schema: str, object_name: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT * FROM metadata_objects
            WHERE connection_name = ? AND lower(schema_name)=lower(?) AND lower(object_name)=lower(?)
            """,
            (connection_name, schema, object_name),
        ).fetchone()
        if row is None:
            raise KeyError(f"metadata object not found: {connection_name}:{schema}.{object_name}")
        item = self._object(row)
        columns = self.connection.execute(
            "SELECT * FROM metadata_columns WHERE object_id = ? ORDER BY ordinal_position, column_name",
            (row["object_id"],),
        ).fetchall()
        item["columns"] = [self._column(column) for column in columns]
        return item

    def tags(self, connection_name: str, schema: str, object_name: str) -> list[dict[str, Any]]:
        return self.inspect(connection_name, schema, object_name)["tags"]

    def schema_context(
        self,
        *,
        connection_name: str | None = None,
        query: str = "",
        limit: int = 500,
    ) -> dict[str, dict[str, str]]:
        assets = self.search_assets(query, connection_name=connection_name, limit=limit)
        context: dict[str, dict[str, str]] = {}
        for asset in assets:
            columns = self.connection.execute(
                "SELECT column_name, data_type FROM metadata_columns WHERE object_id = ? ORDER BY ordinal_position",
                (asset["object_id"],),
            ).fetchall()
            qualified = ".".join(
                part
                for part in (asset.get("catalog"), asset["schema_name"], asset["object_name"])
                if part
            )
            mapping = {str(row["column_name"]): str(row["data_type"] or "UNKNOWN") for row in columns}
            context[qualified] = mapping
            context[asset["object_name"]] = mapping
        return context

    def set_pii(
        self,
        object_id: str,
        column_name: str,
        category: str | None,
        confidence: float | None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE metadata_columns
            SET pii_category = ?, pii_confidence = ?
            WHERE object_id = ? AND column_name = ?
            """,
            (category, confidence, object_id, column_name),
        )
        self.connection.commit()

    @staticmethod
    def _object(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in (
            "tags_json",
            "primary_key_json",
            "foreign_keys_json",
            "partitioning_json",
            "clustering_json",
        ):
            item[key.removesuffix("_json")] = json.loads(item.pop(key) or "[]" if key not in {"partitioning_json", "clustering_json"} else item.pop(key) or "{}")
        return item

    @staticmethod
    def _column(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["nullable"] = bool(item["nullable"])
        item["tags"] = json.loads(item.pop("tags_json") or "[]")
        return item
