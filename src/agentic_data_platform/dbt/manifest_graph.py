"""Deterministic intelligence over dbt artifacts without a warehouse connection."""

from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ARTIFACTS = ("manifest.json", "catalog.json", "run_results.json", "sources.json")


@dataclass(frozen=True)
class DbtArtifacts:
    manifest: dict[str, Any]
    catalog: dict[str, Any] | None = None
    run_results: dict[str, Any] | None = None
    sources: dict[str, Any] | None = None

    @classmethod
    def load(cls, target_dir: str | Path) -> "DbtArtifacts":
        root = Path(target_dir)
        values: dict[str, dict[str, Any] | None] = {}
        for filename in ARTIFACTS:
            path = root / filename
            values[filename.removesuffix(".json")] = json.loads(path.read_text()) if path.is_file() else None
        if values["manifest"] is None:
            raise FileNotFoundError(f"dbt manifest not found: {root / 'manifest.json'}")
        return cls(**values)  # type: ignore[arg-type]


class DbtManifestGraph:
    def __init__(self, artifacts: DbtArtifacts) -> None:
        self.artifacts = artifacts
        manifest = artifacts.manifest
        self.nodes: dict[str, dict[str, Any]] = {}
        for collection in ("nodes", "sources", "exposures", "metrics", "semantic_models", "saved_queries"):
            self.nodes.update(manifest.get(collection, {}))
        self.parents = {key: tuple(value) for key, value in manifest.get("parent_map", {}).items()}
        self.children = {key: tuple(value) for key, value in manifest.get("child_map", {}).items()}
        for node_id, node in self.nodes.items():
            dependencies = tuple(node.get("depends_on", {}).get("nodes", ()))
            if dependencies and node_id not in self.parents:
                self.parents[node_id] = dependencies
            for parent in dependencies:
                existing = list(self.children.get(parent, ()))
                if node_id not in existing:
                    existing.append(node_id)
                self.children[parent] = tuple(existing)

    def resolve(self, reference: str) -> str:
        if reference in self.nodes:
            return reference
        candidates = [
            node_id for node_id, node in self.nodes.items()
            if node.get("name") == reference or node_id.rsplit(".", 1)[-1] == reference
        ]
        if not candidates:
            raise KeyError(f"dbt node not found: {reference}")
        if len(candidates) > 1:
            raise ValueError(f"ambiguous dbt node {reference!r}: {', '.join(sorted(candidates))}")
        return candidates[0]

    def node(self, reference: str) -> dict[str, Any]:
        node_id = self.resolve(reference)
        node = self.nodes[node_id]
        catalog = self.artifacts.catalog or {}
        catalog_node = catalog.get("nodes", {}).get(node_id, {}) or catalog.get("sources", {}).get(node_id, {})
        return {
            "unique_id": node_id,
            "name": node.get("name"),
            "resource_type": node.get("resource_type"),
            "package_name": node.get("package_name"),
            "path": node.get("original_file_path") or node.get("path"),
            "materialized": node.get("config", {}).get("materialized"),
            "database": node.get("database"),
            "schema": node.get("schema"),
            "description": node.get("description"),
            "columns": sorted(catalog_node.get("columns", {})),
            "relation_name": node.get("relation_name"),
            "depends_on": list(node.get("depends_on", {}).get("nodes", ())),
        }

    def summary(self) -> dict[str, Any]:
        counts = Counter(node.get("resource_type", "unknown") for node in self.nodes.values())
        return {
            "resource_counts": dict(sorted(counts.items())),
            "total_nodes": len(self.nodes),
            "artifacts": {name: getattr(self.artifacts, name) is not None for name in ("manifest", "catalog", "run_results", "sources")},
        }

    def _walk(self, reference: str, direction: str, depth: int | None = None) -> list[dict[str, Any]]:
        start = self.resolve(reference)
        graph = self.parents if direction == "upstream" else self.children
        queue = deque((item, 1) for item in graph.get(start, ()))
        visited: set[str] = set()
        result: list[dict[str, Any]] = []
        while queue:
            node_id, node_depth = queue.popleft()
            if node_id in visited or (depth is not None and node_depth > depth):
                continue
            visited.add(node_id)
            if node_id in self.nodes:
                item = self.node(node_id)
                item["depth"] = node_depth
                result.append(item)
            if depth is None or node_depth < depth:
                queue.extend((child, node_depth + 1) for child in graph.get(node_id, ()))
        return sorted(result, key=lambda item: (item["depth"], item["unique_id"]))

    def upstream(self, reference: str, depth: int | None = None) -> list[dict[str, Any]]:
        return self._walk(reference, "upstream", depth)

    def downstream(self, reference: str, depth: int | None = None) -> list[dict[str, Any]]:
        return self._walk(reference, "downstream", depth)

    def tests_for_node(self, reference: str) -> list[dict[str, Any]]:
        node_id = self.resolve(reference)
        tests = []
        for candidate_id, candidate in self.nodes.items():
            if candidate.get("resource_type") != "test":
                continue
            if node_id in candidate.get("depends_on", {}).get("nodes", ()):
                tests.append(self.node(candidate_id))
        return sorted(tests, key=lambda item: item["unique_id"])

    def failed_tests(self) -> list[dict[str, Any]]:
        results = (self.artifacts.run_results or {}).get("results", ())
        failed = []
        for result in results:
            node_id = result.get("unique_id", "")
            if node_id.startswith("test.") and result.get("status") not in {"pass", "success"}:
                failed.append({
                    "unique_id": node_id,
                    "status": result.get("status"),
                    "message": result.get("message"),
                    "failures": result.get("failures"),
                })
        return failed

    def lineage(self, reference: str, depth: int | None = None) -> dict[str, Any]:
        return {"node": self.node(reference), "upstream": self.upstream(reference, depth), "downstream": self.downstream(reference, depth)}

    def impact(self, reference: str, depth: int | None = None) -> dict[str, Any]:
        node_id = self.resolve(reference)
        direct = self.downstream(node_id, 1)
        transitive = self.downstream(node_id, depth)
        affected_tests = [item for item in transitive if item["resource_type"] == "test"]
        facts = [item for item in transitive if item["resource_type"] == "model" and item["name"].startswith("fact_")]
        marts = [item for item in transitive if item["resource_type"] == "model" and item["name"].startswith("mart_")]
        severity = "HIGH" if marts or len(transitive) >= 10 else "MEDIUM" if facts or len(transitive) >= 3 else "LOW"
        return {
            "changed_asset": self.node(node_id),
            "direct_downstream": direct,
            "transitive_downstream": transitive,
            "affected_facts": facts,
            "affected_marts": marts,
            "affected_tests": affected_tests,
            "severity": severity,
            "recommended_selector": f"{self.nodes[node_id].get('name', node_id)}+",
        }

    def modified_impact(self, previous_manifest: dict[str, Any]) -> dict[str, Any]:
        from agentic_data_platform.dbt.intelligence import get_changed_nodes

        changed = get_changed_nodes(previous_manifest, self.artifacts.manifest)
        return {"changed_nodes": changed, "impacts": [self.impact(node_id) for node_id in changed if node_id in self.nodes]}
