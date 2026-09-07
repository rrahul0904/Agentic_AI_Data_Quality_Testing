"""Cross-system asset graph assembled from source DDL, Airflow AST and dbt artifacts."""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentic_data_platform.context.graph import ContextGraph, GraphNode
from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.platform.discovery import PlatformDiscovery


_TABLE = re.compile(r"(?im)^\s*CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([\w.$\"]+)")


class PlatformAssetGraph:
    def __init__(self, graph: ContextGraph, project: Path) -> None:
        self.graph = graph
        self.project = project

    @classmethod
    def build(cls, project: str | Path) -> "PlatformAssetGraph":
        discovery = PlatformDiscovery(project)
        root = Path(discovery.inventory()["hospitality_project"])
        instance = cls(ContextGraph(), root)
        instance._add_sources()
        airflow = instance._add_airflow()
        instance._add_dbt(airflow)
        return instance

    def _node(self, kind: str, name: str, **properties: Any) -> GraphNode:
        return self.graph.upsert_node(kind=kind, name=name, properties=properties)

    def _connect(self, source: GraphNode, target: GraphNode, edge_type: str, **properties: Any) -> None:
        self.graph.upsert_edge(source_id=source.node_id, target_id=target.node_id, edge_type=edge_type, properties=properties)

    def _add_sources(self) -> None:
        for system in ("oracle", "postgres"):
            path = self.project / "sources" / system / "ddl" / "001_source_schema.sql"
            if not path.is_file():
                continue
            for match in _TABLE.finditer(path.read_text(encoding="utf-8")):
                table = match.group(1).strip('"')
                self._node("source_table", f"{system}.{table}", system=system, table=table, file=str(path))
        feeds = self.project / "data_generator" / "generate_file_data.py"
        if feeds.is_file():
            tree = ast.parse(feeds.read_text(encoding="utf-8"), filename=str(feeds))
            for statement in tree.body:
                value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
                target_names = []
                if isinstance(statement, ast.Assign):
                    target_names = [node.id for node in statement.targets if isinstance(node, ast.Name)]
                elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    target_names = [statement.target.id]
                if "FEEDS" in target_names and isinstance(value, ast.Dict):
                    for key in value.keys:
                        filename = ast.literal_eval(key)
                        self._node("source_file", filename, system="files", file=str(feeds))

    def _resolve_source(self, system: str, entity: str) -> GraphNode | None:
        name = entity if system == "files" else f"{system}.{entity}"
        matches = self.graph.find_nodes(name)
        return matches[0] if len(matches) == 1 else None

    def _add_airflow(self) -> AirflowProject:
        airflow = AirflowProject.scan(self.project)
        for dag in airflow.dags.values():
            dag_node = self._node("airflow_dag", dag.dag_id, file=dag.file, schedule=dag.schedule, source=dag.source)
            for task in dag.tasks:
                task_node = self._node("airflow_task", f"{dag.dag_id}.{task}", dag_id=dag.dag_id, task_id=task)
                self._connect(dag_node, task_node, "contains")
            if dag.source:
                for entity in dag.entities:
                    source = self._resolve_source(dag.source, entity)
                    if source:
                        self._connect(source, dag_node, "extracts", entity=entity)
                    logical_name = f"HOSPITALITY_DW.RAW.{dag.source.upper()}_{Path(entity).stem.upper()}"
                    raw = self._node(
                        "warehouse_table", logical_name, layer="RAW", logical=True,
                        physical_target="HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS",
                        source_system=dag.source, source_entity=entity,
                    )
                    self._connect(dag_node, raw, "loads", entity=entity)
            for dependency in dag.dag_dependencies:
                target = self._node("airflow_dag", dependency)
                self._connect(dag_node, target, "depends_on")
        return airflow

    @staticmethod
    def _dbt_kind(node: dict[str, Any]) -> str:
        resource_type = node.get("resource_type")
        if resource_type == "source":
            return "dbt_source"
        if resource_type == "test":
            return "dbt_test"
        if resource_type == "snapshot":
            return "dbt_snapshot"
        if resource_type == "model" and str(node.get("name", "")).startswith("mart_"):
            return "mart"
        return "dbt_model"

    def _logical_raw_for_stage(self, name: str) -> GraphNode | None:
        match = re.match(r"stg_(oracle|postgres|file)_(.+)", name)
        if not match:
            return None
        system, entity = match.groups()
        source_system = "files" if system == "file" else system
        expected = entity.upper()
        candidates = [
            node for node in self.graph.list_nodes()
            if node.kind == "warehouse_table" and node.properties.get("source_system") == source_system
        ]
        exact = [node for node in candidates if str(node.properties.get("source_entity", "")).split(".")[0].upper() == expected]
        return sorted(exact, key=lambda item: item.name)[0] if exact else None

    def _add_dbt(self, airflow: AirflowProject) -> None:
        del airflow  # Airflow-derived RAW nodes are already in the graph.
        target = self.project / "dbt" / "target"
        if not (target / "manifest.json").is_file():
            return
        dbt_graph = DbtManifestGraph(DbtArtifacts.load(target))
        nodes: dict[str, GraphNode] = {}
        for unique_id, item in dbt_graph.nodes.items():
            if item.get("resource_type") not in {"source", "model", "test", "snapshot", "exposure", "metric"}:
                continue
            kind = self._dbt_kind(item)
            if item.get("resource_type") == "source":
                name = f"{item.get('source_name')}.{item.get('name')}"
            else:
                name = item.get("name") or unique_id
            nodes[unique_id] = self._node(
                kind, name, unique_id=unique_id, resource_type=item.get("resource_type"),
                relation_name=item.get("relation_name"), file=item.get("original_file_path"),
            )
        for unique_id, target_node in nodes.items():
            item = dbt_graph.nodes[unique_id]
            for dependency in item.get("depends_on", {}).get("nodes", ()):
                source_node = nodes.get(dependency)
                if source_node:
                    edge = "tests" if item.get("resource_type") == "test" else "transforms"
                    self._connect(source_node, target_node, edge)
            logical_raw = self._logical_raw_for_stage(str(item.get("name", "")))
            if logical_raw:
                self._connect(logical_raw, target_node, "transforms", derived_from="source_entity")

    def _resolve(self, reference: str) -> GraphNode:
        matches = self.graph.find_nodes(reference)
        if not matches:
            raise KeyError(f"platform asset not found: {reference}")
        if len(matches) > 1:
            exact = [node for node in matches if node.name.casefold() == reference.casefold()]
            if len(exact) == 1:
                return exact[0]
            options = ", ".join(f"{node.kind}:{node.name}" for node in matches)
            raise ValueError(f"ambiguous platform asset {reference!r}: {options}")
        return matches[0]

    def summary(self) -> dict[str, Any]:
        nodes = self.graph.list_nodes()
        edges = self.graph.list_edges()
        return {
            "project": str(self.project), "node_count": len(nodes), "edge_count": len(edges),
            "node_types": dict(sorted(Counter(node.kind for node in nodes).items())),
            "edge_types": dict(sorted(Counter(edge.edge_type for edge in edges).items())),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.summary(), "nodes": [asdict(node) for node in self.graph.list_nodes()],
            "edges": [asdict(edge) for edge in self.graph.list_edges()],
        }

    def lineage(self, reference: str, *, depth: int | None = None) -> dict[str, Any]:
        node = self._resolve(reference)
        return {
            "asset": asdict(node), "upstream": self.graph.traverse(node.node_id, direction="in", depth=depth),
            "downstream": self.graph.traverse(node.node_id, direction="out", depth=depth),
        }

    def impact(self, reference: str, *, depth: int | None = None) -> dict[str, Any]:
        node = self._resolve(reference)
        downstream = self.graph.traverse(node.node_id, direction="out", depth=depth)
        marts = [item for item in downstream if item["kind"] == "mart"]
        tests = [item for item in downstream if item["kind"] == "dbt_test"]
        severity = "HIGH" if marts or len(downstream) >= 10 else "MEDIUM" if downstream else "LOW"
        return {
            "changed_asset": asdict(node), "downstream": downstream, "affected_marts": marts,
            "affected_tests": tests, "severity": severity,
        }
