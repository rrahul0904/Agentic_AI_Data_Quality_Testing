"""Small SQLite metadata catalog used for local search and autocomplete."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class MetadataIndex:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, metadata_json TEXT NOT NULL, UNIQUE(kind, name));
        CREATE TABLE IF NOT EXISTS columns (asset_id TEXT NOT NULL, name TEXT NOT NULL, data_type TEXT, pii INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL, UNIQUE(asset_id, name));
        CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(name);
        CREATE INDEX IF NOT EXISTS idx_columns_name ON columns(name);
        """)
        self.connection.commit()

    def upsert_asset(self, asset_id: str, kind: str, name: str, metadata: dict[str, Any] | None = None) -> None:
        self.connection.execute("INSERT INTO assets VALUES (?, ?, ?, ?) ON CONFLICT(asset_id) DO UPDATE SET kind=excluded.kind, name=excluded.name, metadata_json=excluded.metadata_json", (asset_id, kind, name, json.dumps(metadata or {}, sort_keys=True)))
        self.connection.commit()

    def upsert_column(self, asset_id: str, name: str, data_type: str | None = None, *, pii: bool = False, metadata: dict[str, Any] | None = None) -> None:
        self.connection.execute("INSERT INTO columns VALUES (?, ?, ?, ?, ?) ON CONFLICT(asset_id, name) DO UPDATE SET data_type=excluded.data_type, pii=excluded.pii, metadata_json=excluded.metadata_json", (asset_id, name, data_type, int(pii), json.dumps(metadata or {}, sort_keys=True)))
        self.connection.commit()

    def search_assets(self, query: str, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM assets WHERE lower(name) LIKE ?"
        params: list[Any] = [f"%{query.casefold()}%"]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY name LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def search_columns(self, query: str, *, pii_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT c.*, a.kind, a.name AS asset_name FROM columns c JOIN assets a ON a.asset_id = c.asset_id WHERE lower(c.name) LIKE ?"
        params: list[Any] = [f"%{query.casefold()}%"]
        if pii_only:
            sql += " AND c.pii = 1"
        sql += " ORDER BY c.name LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def pii_assets(self) -> list[dict[str, Any]]:
        return self.search_columns("", pii_only=True)
