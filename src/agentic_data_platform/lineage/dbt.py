"""Project-wide dbt column graph built from compiled SQL and dbt artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentic_data_platform.dbt.manifest_graph import DbtArtifacts
from agentic_data_platform.lineage.engine import analyze_column_lineage


@dataclass(frozen=True, order=True)
class ColumnNode:
    asset_id: str
    column: str
    resource_type: str
    relation_name: str | None = None

    @property
    def node_id(self) -> str:
        return f"{self.asset_id}.{self.column}"


@dataclass(frozen=True, order=True)
class ColumnEdge:
    source: str
    target: str
    confidence: str
    expression: str


class DbtColumnGraph:
    def __init__(self, artifacts: DbtArtifacts, *, dialect: str = "snowflake") -> None:
        self.artifacts = artifacts
        self.dialect = dialect
        manifest = artifacts.manifest
        self.nodes: dict[str, dict[str, Any]] = {}
        for collection in ("nodes", "sources", "exposures"):
            self.nodes.update(manifest.get(collection, {}))

        self.column_nodes: dict[str, ColumnNode] = {}
        self.edges: set[ColumnEdge] = set()
        self.unresolved: list[dict[str, Any]] = []
        self._relation_lookup: dict[str, str] = {}
        self._build_relation_lookup()
        self._schema = self._build_schema()
        self._build()

    @classmethod
    def load(cls, target_dir: str | Path, *, dialect: str = "snowflake") -> "DbtColumnGraph":
        return cls(DbtArtifacts.load(target_dir), dialect=dialect)

    def _build_relation_lookup(self) -> None:
        for node_id, node in self.nodes.items():
            names = {
                str(node.get("name") or ""),
                str(node.get("alias") or ""),
                str(node.get("relation_name") or ""),
            }
            database = node.get("database")
            schema = node.get("schema")
            identifier = node.get("identifier") or node.get("alias") or node.get("name")
            if identifier:
                names.add(str(identifier))
                if schema:
                    names.add(f"{schema}.{identifier}")
                if database and schema:
                    names.add(f"{database}.{schema}.{identifier}")
            for name in names:
                if not name:
                    continue
                self._relation_lookup[name.casefold()] = node_id
                self._relation_lookup[name.split(".")[-1].casefold()] = node_id

    def _columns_for(self, node_id: str, node: dict[str, Any]) -> dict[str, str]:
        catalog = self.artifacts.catalog or {}
        catalog_node = (
            catalog.get("nodes", {}).get(node_id)
            or catalog.get("sources", {}).get(node_id)
            or {}
        )
        result: dict[str, str] = {}
        for name, value in (catalog_node.get("columns") or {}).items():
            result[str(name)] = (
                str(value.get("type") or "UNKNOWN")
                if isinstance(value, dict)
                else "UNKNOWN"
            )
        for name, value in (node.get("columns") or {}).items():
            result.setdefault(
                str(name),
                str(value.get("data_type") or "UNKNOWN")
                if isinstance(value, dict)
                else "UNKNOWN",
            )
        return result

    def _build_schema(self) -> dict[str, dict[str, str]]:
        schema: dict[str, dict[str, str]] = {}
        for node_id, node in self.nodes.items():
            columns = self._columns_for(node_id, node)
            if not columns:
                continue
            relation = str(node.get("relation_name") or node.get("name") or "")
            names = {relation, str(node.get("name") or ""), str(node.get("alias") or "")}
            for name in names:
                if name:
                    schema[name] = columns
                    schema[name.split(".")[-1]] = columns
        return schema

    def _column_node(self, asset_id: str, column: str) -> ColumnNode:
        node = self.nodes[asset_id]
        item = ColumnNode(
            asset_id=asset_id,
            column=column,
            resource_type=str(node.get("resource_type") or "unknown"),
            relation_name=node.get("relation_name"),
        )
        self.column_nodes[item.node_id] = item
        return item

    def _resolve_asset(self, table: str) -> str | None:
        key = table.casefold()
        return self._relation_lookup.get(key) or self._relation_lookup.get(table.split(".")[-1].casefold())

    def _build(self) -> None:
        for asset_id, node in self.nodes.items():
            for column in self._columns_for(asset_id, node):
                self._column_node(asset_id, column)

        for asset_id, node in self.nodes.items():
            if node.get("resource_type") not in {"model", "snapshot"}:
                continue
            sql = node.get("compiled_code") or node.get("compiled_sql")
            if not sql:
                self.unresolved.append({"asset_id": asset_id, "reason": "compiled SQL unavailable"})
                continue
            result = analyze_column_lineage(sql, dialect=self.dialect, schema=self._schema)
            if not result.get("parseable"):
                self.unresolved.append(
                    {"asset_id": asset_id, "reason": result.get("error") or "parse failure"}
                )
                continue

            for mapping in result.get("mappings", ()):
                target_name = str(mapping.get("target") or "")
                if not target_name:
                    continue
                target = self._column_node(asset_id, target_name)
                mapping_sources = mapping.get("sources", ())
                if not mapping_sources and mapping.get("unresolved_references"):
                    self.unresolved.append(
                        {
                            "asset_id": asset_id,
                            "column": target_name,
                            "reason": "; ".join(mapping["unresolved_references"]),
                        }
                    )
                for source in mapping_sources:
                    source_asset = self._resolve_asset(str(source.get("table") or ""))
                    if not source_asset:
                        self.unresolved.append(
                            {
                                "asset_id": asset_id,
                                "column": target_name,
                                "source": source,
                                "reason": "source relation not found in manifest/catalog",
                            }
                        )
                        continue
                    source_node = self._column_node(source_asset, str(source.get("column") or ""))
                    self.edges.add(
                        ColumnEdge(
                            source=source_node.node_id,
                            target=target.node_id,
                            confidence=str(mapping.get("confidence") or "medium"),
                            expression=str(mapping.get("expression") or ""),
                        )
                    )

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for node in self.column_nodes.values():
            counts[node.resource_type] += 1
        return {
            "column_nodes": len(self.column_nodes),
            "edges": len(self.edges),
            "unresolved_count": len(self.unresolved),
            "resource_types": dict(sorted(counts.items())),
        }

    def graph(self) -> dict[str, Any]:
        return {
            "nodes": [
                asdict(node) | {"node_id": node.node_id}
                for node in sorted(self.column_nodes.values())
            ],
            "edges": [asdict(edge) for edge in sorted(self.edges)],
            "unresolved": list(self.unresolved),
            "summary": self.summary(),
        }

    def _adjacency(self, direction: str) -> dict[str, list[ColumnEdge]]:
        result: dict[str, list[ColumnEdge]] = defaultdict(list)
        for edge in self.edges:
            key = edge.target if direction == "upstream" else edge.source
            result[key].append(edge)
        return result

    def resolve_column(self, asset: str, column: str) -> str:
        asset_cf = asset.casefold()
        candidates = [
            node.node_id
            for node in self.column_nodes.values()
            if node.column.casefold() == column.casefold()
            and (
                node.asset_id.casefold() == asset_cf
                or node.asset_id.rsplit(".", 1)[-1].casefold() == asset_cf
                or (node.relation_name and node.relation_name.casefold() == asset_cf)
                or (
                    node.relation_name
                    and node.relation_name.split(".")[-1].casefold() == asset_cf
                )
            )
        ]
        if not candidates:
            raise KeyError(f"column not found: {asset}.{column}")
        if len(candidates) > 1:
            raise ValueError(
                f"ambiguous column reference {asset}.{column}: {', '.join(sorted(candidates))}"
            )
        return candidates[0]

    def _walk(self, node_id: str, direction: str, depth: int | None = None) -> list[dict[str, Any]]:
        if node_id not in self.column_nodes:
            raise KeyError(f"column node not found: {node_id}")
        adjacency = self._adjacency(direction)
        queue = deque([(node_id, 0)])
        visited = {node_id}
        result = []
        while queue:
            current, current_depth = queue.popleft()
            if depth is not None and current_depth >= depth:
                continue
            for edge in sorted(adjacency.get(current, ()), key=lambda item: (item.source, item.target)):
                nxt = edge.source if direction == "upstream" else edge.target
                if nxt in visited:
                    continue
                visited.add(nxt)
                node = self.column_nodes[nxt]
                result.append(
                    asdict(node)
                    | {
                        "node_id": node.node_id,
                        "depth": current_depth + 1,
                        "via": asdict(edge),
                    }
                )
                queue.append((nxt, current_depth + 1))
        return result

    def upstream(self, asset: str, column: str, depth: int | None = None) -> dict[str, Any]:
        node_id = self.resolve_column(asset, column)
        return {"column": node_id, "upstream": self._walk(node_id, "upstream", depth)}

    def downstream(self, asset: str, column: str, depth: int | None = None) -> dict[str, Any]:
        node_id = self.resolve_column(asset, column)
        return {"column": node_id, "downstream": self._walk(node_id, "downstream", depth)}

    def path(
        self,
        source_asset: str,
        source_column: str,
        target_asset: str,
        target_column: str,
    ) -> dict[str, Any]:
        start = self.resolve_column(source_asset, source_column)
        target = self.resolve_column(target_asset, target_column)
        adjacency = self._adjacency("downstream")
        queue = deque([(start, [start])])
        visited = {start}
        while queue:
            current, path = queue.popleft()
            if current == target:
                return {"found": True, "path": path, "hops": len(path) - 1}
            for edge in adjacency.get(current, ()):
                nxt = edge.target
                if nxt in visited:
                    continue
                visited.add(nxt)
                queue.append((nxt, [*path, nxt]))
        return {"found": False, "path": [], "hops": None}

    def impact(self, asset: str, column: str, depth: int | None = None) -> dict[str, Any]:
        downstream = self.downstream(asset, column, depth)["downstream"]
        counts: dict[str, int] = defaultdict(int)
        for item in downstream:
            counts[str(item["resource_type"])] += 1
        severity = "HIGH" if len(downstream) >= 10 else "MEDIUM" if downstream else "LOW"
        return {
            "column": self.resolve_column(asset, column),
            "downstream": downstream,
            "affected_count": len(downstream),
            "resource_counts": dict(sorted(counts.items())),
            "severity": severity,
        }

    def diff(self, other: "DbtColumnGraph") -> dict[str, Any]:
        before = {(edge.source, edge.target, edge.expression) for edge in self.edges}
        after = {(edge.source, edge.target, edge.expression) for edge in other.edges}
        added = sorted(after - before)
        removed = sorted(before - after)
        return {
            "added_edges": [
                {"source": source, "target": target, "expression": expression}
                for source, target, expression in added
            ],
            "removed_edges": [
                {"source": source, "target": target, "expression": expression}
                for source, target, expression in removed
            ],
            "changed": bool(added or removed),
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "nodes": sorted(self.column_nodes),
                "edges": sorted(
                    (edge.source, edge.target, edge.expression) for edge in self.edges
                ),
            },
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def build_dbt_column_graph(target_dir: str | Path, dialect: str = "snowflake") -> DbtColumnGraph:
    return DbtColumnGraph.load(target_dir, dialect=dialect)
