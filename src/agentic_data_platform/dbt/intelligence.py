from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _all_nodes(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {**manifest.get("nodes", {}), **manifest.get("sources", {})}


def _signature(node: dict[str, Any]) -> tuple[Any, ...]:
    return (node.get("checksum", {}).get("checksum"), node.get("raw_code"), node.get("compiled_code"), node.get("config"), node.get("depends_on"))


def get_changed_nodes(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    old, new = _all_nodes(previous), _all_nodes(current)
    return sorted(node_id for node_id, node in new.items() if node_id not in old or _signature(node) != _signature(old[node_id]))


def _walk(graph: dict[str, list[str]], node_id: str) -> list[str]:
    visited: set[str] = set()
    queue = list(graph.get(node_id, []))
    while queue:
        item = queue.pop(0)
        if item not in visited:
            visited.add(item)
            queue.extend(graph.get(item, []))
    return sorted(visited)


def get_downstream_nodes(manifest: dict[str, Any], node_id: str) -> list[str]:
    return _walk(manifest.get("child_map", {}), node_id)


def get_upstream_nodes(manifest: dict[str, Any], node_id: str) -> list[str]:
    return _walk(manifest.get("parent_map", {}), node_id)


@dataclass(frozen=True)
class DbtProjectSnapshot:
    manifest: dict[str, Any]
    run_results: dict[str, Any] | None = None
    catalog: dict[str, Any] | None = None
    sources: dict[str, Any] | None = None


def selective_build_command(project_dir: str, node_id: str) -> tuple[str, ...]:
    return ("dbt", "build", "--project-dir", project_dir, "--select", f"{node_id}+")


def state_test_command(project_dir: str) -> tuple[str, ...]:
    return ("dbt", "test", "--project-dir", project_dir, "--select", "state:modified+")
