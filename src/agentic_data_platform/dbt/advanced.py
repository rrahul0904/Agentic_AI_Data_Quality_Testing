"""Advanced deterministic dbt artifact intelligence for local/offline use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_data_platform.dbt.intelligence import get_changed_nodes
from agentic_data_platform.dbt.manifest_graph import DbtManifestGraph
from agentic_data_platform.sql.intelligence import review_sql


def incremental_analysis(graph: DbtManifestGraph) -> dict[str, Any]:
    models = []
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "model" or node.get("config", {}).get("materialized") != "incremental":
            continue
        config = node.get("config", {})
        models.append({
            "unique_id": node_id,
            "name": node.get("name"),
            "unique_key": config.get("unique_key"),
            "incremental_strategy": config.get("incremental_strategy"),
            "on_schema_change": config.get("on_schema_change"),
            "has_unique_key": bool(config.get("unique_key")),
            "risk": "WARN" if not config.get("unique_key") else "PASS",
        })
    return {
        "count": len(models),
        "without_unique_key": sum(not item["has_unique_key"] for item in models),
        "models": sorted(models, key=lambda item: item["name"] or ""),
    }


def snapshot_analysis(graph: DbtManifestGraph) -> dict[str, Any]:
    snapshots = []
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "snapshot":
            continue
        config = node.get("config", {})
        snapshots.append({
            "unique_id": node_id,
            "name": node.get("name"),
            "strategy": config.get("strategy"),
            "unique_key": config.get("unique_key"),
            "updated_at": config.get("updated_at"),
            "target_schema": config.get("schema"),
            "status": "PASS" if config.get("unique_key") and config.get("strategy") else "WARN",
        })
    return {"count": len(snapshots), "snapshots": sorted(snapshots, key=lambda item: item["name"] or "")}


def macro_analysis(graph: DbtManifestGraph) -> dict[str, Any]:
    macros = graph.artifacts.manifest.get("macros", {})
    items = [{
        "unique_id": unique_id,
        "name": macro.get("name"),
        "package_name": macro.get("package_name"),
        "path": macro.get("original_file_path") or macro.get("path"),
        "arguments": macro.get("arguments", []),
    } for unique_id, macro in macros.items()]
    package_counts: dict[str, int] = {}
    for item in items:
        package = item["package_name"] or "unknown"
        package_counts[package] = package_counts.get(package, 0) + 1
    return {"count": len(items), "package_counts": dict(sorted(package_counts.items())), "macros": items}


def failed_models(graph: DbtManifestGraph) -> dict[str, Any]:
    results = (graph.artifacts.run_results or {}).get("results", ())
    items = []
    for result in results:
        unique_id = result.get("unique_id", "")
        if unique_id.startswith("model.") and result.get("status") not in {"pass", "success"}:
            items.append({
                "unique_id": unique_id,
                "status": result.get("status"),
                "message": result.get("message"),
                "execution_time": result.get("execution_time"),
            })
    return {"count": len(items), "models": items}


def source_freshness_configuration(graph: DbtManifestGraph) -> dict[str, Any]:
    sources = []
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "source":
            continue
        freshness = node.get("freshness") or {}
        sources.append({
            "unique_id": node_id,
            "name": node.get("name"),
            "source_name": node.get("source_name"),
            "loaded_at_field": node.get("loaded_at_field"),
            "freshness": freshness,
            "configured": bool(freshness) or bool(node.get("loaded_at_field")),
        })
    return {
        "count": len(sources),
        "configured": sum(item["configured"] for item in sources),
        "unconfigured": sum(not item["configured"] for item in sources),
        "sources": sources,
    }


def leaf_model_candidates(graph: DbtManifestGraph) -> dict[str, Any]:
    candidates = []
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "model":
            continue
        non_test_children = [
            child for child in graph.children.get(node_id, ())
            if graph.nodes.get(child, {}).get("resource_type") != "test"
        ]
        name = node.get("name") or node_id
        if not non_test_children and not name.startswith(("mart_", "fact_", "dim_")):
            candidates.append({
                "unique_id": node_id,
                "name": name,
                "path": node.get("original_file_path"),
                "reason": "no non-test downstream nodes; review before removal",
            })
    return {"count": len(candidates), "candidates": sorted(candidates, key=lambda item: item["name"])}


def compiled_sql_review(graph: DbtManifestGraph, *, limit: int = 100) -> dict[str, Any]:
    reviewed = []
    total_findings = 0
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "model":
            continue
        sql = node.get("compiled_code") or node.get("compiled_sql")
        if not sql:
            continue
        result = review_sql(sql, "snowflake")
        findings = result.get("findings", [])
        total_findings += len(findings)
        reviewed.append({
            "unique_id": node_id,
            "name": node.get("name"),
            "status": result.get("status"),
            "finding_count": len(findings),
            "findings": findings[:10],
        })
        if len(reviewed) >= limit:
            break
    return {
        "models_reviewed": len(reviewed),
        "total_findings": total_findings,
        "failing_models": sum(item["status"] == "FAIL" for item in reviewed),
        "models": reviewed,
    }


def state_compare(graph: DbtManifestGraph, previous_manifest_path: str | Path) -> dict[str, Any]:
    path = Path(previous_manifest_path)
    previous = json.loads(path.read_text())
    current = graph.artifacts.manifest
    changed = get_changed_nodes(previous, current)
    previous_nodes = {**previous.get("nodes", {}), **previous.get("sources", {})}
    current_nodes = {**current.get("nodes", {}), **current.get("sources", {})}
    removed = sorted(set(previous_nodes) - set(current_nodes))
    added = sorted(set(current_nodes) - set(previous_nodes))
    impacts = [graph.impact(node_id, 8) for node_id in changed if node_id in graph.nodes]
    return {
        "changed_nodes": changed,
        "added_nodes": added,
        "removed_nodes": removed,
        "impact_count": len(impacts),
        "impacts": impacts,
    }
