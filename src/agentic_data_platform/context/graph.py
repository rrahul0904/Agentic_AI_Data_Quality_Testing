"""Small persistent directed graph backed by SQLite-compatible relational tables."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_data_platform.models import new_id, utc_now


@dataclass(frozen=True)
class GraphNode:
    kind: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    node_id: str = field(default_factory=lambda: new_id("asset"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class GraphEdge:
    source_id: str
    target_id: str
    edge_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    edge_id: str = field(default_factory=lambda: new_id("edge"))
    created_at: str = field(default_factory=utc_now)


class ContextGraph:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS asset_nodes (
              node_id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
              properties_json TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(kind, name)
            );
            CREATE TABLE IF NOT EXISTS asset_edges (
              edge_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
              edge_type TEXT NOT NULL, properties_json TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(source_id, target_id, edge_type)
            );
            CREATE INDEX IF NOT EXISTS idx_asset_edges_source ON asset_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_asset_edges_target ON asset_edges(target_id);
            """
        )
        self._connection.commit()

    @staticmethod
    def _node(row: sqlite3.Row) -> GraphNode:
        return GraphNode(row["kind"], row["name"], json.loads(row["properties_json"]), row["node_id"], row["created_at"])

    def upsert_node(self, node: GraphNode | None = None, *, kind: str | None = None, name: str | None = None, properties: dict[str, Any] | None = None) -> GraphNode:
        item = node or GraphNode(kind or "asset", name or "", properties or {})
        existing = self._connection.execute("SELECT * FROM asset_nodes WHERE kind = ? AND name = ?", (item.kind, item.name)).fetchone()
        if existing:
            node_id = existing["node_id"]
            self._connection.execute("UPDATE asset_nodes SET properties_json = ? WHERE node_id = ?", (json.dumps(item.properties), node_id))
            self._connection.commit()
            return GraphNode(item.kind, item.name, item.properties, node_id, existing["created_at"])
        self._connection.execute("INSERT INTO asset_nodes VALUES (?, ?, ?, ?, ?)", (item.node_id, item.kind, item.name, json.dumps(item.properties), item.created_at))
        self._connection.commit()
        return item

    def upsert_edge(self, edge: GraphEdge | None = None, *, source_id: str | None = None, target_id: str | None = None, edge_type: str | None = None, properties: dict[str, Any] | None = None) -> GraphEdge:
        item = edge or GraphEdge(source_id or "", target_id or "", edge_type or "REFERENCES", properties or {})
        if not self._connection.execute("SELECT 1 FROM asset_nodes WHERE node_id = ?", (item.source_id,)).fetchone() or not self._connection.execute("SELECT 1 FROM asset_nodes WHERE node_id = ?", (item.target_id,)).fetchone():
            raise ValueError("graph edges require existing source and target nodes")
        existing = self._connection.execute("SELECT * FROM asset_edges WHERE source_id = ? AND target_id = ? AND edge_type = ?", (item.source_id, item.target_id, item.edge_type)).fetchone()
        if existing:
            self._connection.execute("UPDATE asset_edges SET properties_json = ? WHERE edge_id = ?", (json.dumps(item.properties), existing["edge_id"]))
            self._connection.commit()
            return GraphEdge(item.source_id, item.target_id, item.edge_type, item.properties, existing["edge_id"], existing["created_at"])
        self._connection.execute("INSERT INTO asset_edges VALUES (?, ?, ?, ?, ?, ?)", (item.edge_id, item.source_id, item.target_id, item.edge_type, json.dumps(item.properties), item.created_at))
        self._connection.commit()
        return item

    def get_node(self, node_id: str) -> GraphNode | None:
        row = self._connection.execute("SELECT * FROM asset_nodes WHERE node_id = ?", (node_id,)).fetchone()
        return self._node(row) if row else None

    @staticmethod
    def _edge(row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            row["source_id"], row["target_id"], row["edge_type"],
            json.loads(row["properties_json"]), row["edge_id"], row["created_at"],
        )

    def list_nodes(self) -> list[GraphNode]:
        rows = self._connection.execute("SELECT * FROM asset_nodes ORDER BY kind, name").fetchall()
        return [self._node(row) for row in rows]

    def list_edges(self) -> list[GraphEdge]:
        rows = self._connection.execute("SELECT * FROM asset_edges ORDER BY edge_type, source_id, target_id").fetchall()
        return [self._edge(row) for row in rows]

    def find_nodes(self, reference: str, *, kind: str | None = None) -> list[GraphNode]:
        needle = reference.casefold()
        return [
            node for node in self.list_nodes()
            if (kind is None or node.kind == kind)
            and (node.name.casefold() == needle or node.name.rsplit(".", 1)[-1].casefold() == needle)
        ]

    def neighbors(self, node_id: str, *, direction: str = "out") -> list[GraphNode]:
        if direction not in {"out", "in"}:
            raise ValueError("direction must be 'out' or 'in'")
        join = "target_id" if direction == "out" else "source_id"
        key = "source_id" if direction == "out" else "target_id"
        rows = self._connection.execute(f"SELECT n.* FROM asset_edges e JOIN asset_nodes n ON n.node_id = e.{join} WHERE e.{key} = ? ORDER BY n.name", (node_id,)).fetchall()
        return [self._node(row) for row in rows]

    def _traverse(self, node_id: str, direction: str) -> list[GraphNode]:
        visited: set[str] = set()
        frontier = [node_id]
        results: list[GraphNode] = []
        while frontier:
            current = frontier.pop(0)
            for item in self.neighbors(current, direction=direction):
                if item.node_id not in visited:
                    visited.add(item.node_id)
                    results.append(item)
                    frontier.append(item.node_id)
        return results

    def upstream(self, node_id: str) -> list[GraphNode]:
        return self._traverse(node_id, "in")

    def downstream(self, node_id: str) -> list[GraphNode]:
        return self._traverse(node_id, "out")

    def impact(self, node_id: str) -> list[GraphNode]:
        return self.downstream(node_id)

    def traverse(self, node_id: str, *, direction: str, depth: int | None = None) -> list[dict[str, Any]]:
        if direction not in {"out", "in"}:
            raise ValueError("direction must be 'out' or 'in'")
        visited: set[str] = {node_id}
        frontier: list[tuple[str, int]] = [(node_id, 0)]
        result: list[dict[str, Any]] = []
        while frontier:
            current, current_depth = frontier.pop(0)
            if depth is not None and current_depth >= depth:
                continue
            for node in self.neighbors(current, direction=direction):
                if node.node_id in visited:
                    continue
                visited.add(node.node_id)
                item_depth = current_depth + 1
                result.append({
                    "node_id": node.node_id, "kind": node.kind, "name": node.name,
                    "properties": node.properties, "depth": item_depth,
                })
                frontier.append((node.node_id, item_depth))
        return sorted(result, key=lambda item: (item["depth"], item["kind"], item["name"]))
