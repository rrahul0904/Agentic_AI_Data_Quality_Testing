"""Governance orchestration: PII propagation, policy checks, and sensitive access."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable, Mapping, Sequence

from agentic_data_platform.governance.pii import classify_column, scan_query
from agentic_data_platform.governance.rbac import sensitive_access


def propagate_pii(
    graph: Mapping[str, Any],
    findings: Iterable[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.7,
) -> dict[str, Any]:
    """Propagate PII classifications through a column-lineage graph.

    Graph edges must use source/target column node ids. Classification is only
    propagated from evidence-backed source findings and never upgraded in
    confidence while traversing derived columns.
    """

    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges", ()):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            adjacency[source].append(target)

    seeds: dict[str, dict[str, Any]] = {}
    for finding in findings:
        node_id = str(
            finding.get("node_id")
            or (
                f"{finding.get('asset_id')}.{finding.get('column')}"
                if finding.get("asset_id") and finding.get("column")
                else ""
            )
        )
        confidence = float(finding.get("confidence") or 0)
        if node_id and confidence >= minimum_confidence:
            current = seeds.get(node_id)
            if current is None or confidence > float(current.get("confidence") or 0):
                seeds[node_id] = dict(finding) | {"node_id": node_id}

    propagated: list[dict[str, Any]] = []
    seen_by_category: set[tuple[str, str]] = set()
    for source_node, seed in seeds.items():
        category = str(seed.get("category") or "unknown")
        queue = deque([(source_node, 0, [source_node])])
        visited = {source_node}
        while queue:
            current, depth, path = queue.popleft()
            for target in adjacency.get(current, ()):
                if target in visited:
                    continue
                visited.add(target)
                next_path = [*path, target]
                key = (target, category)
                if key not in seen_by_category:
                    seen_by_category.add(key)
                    propagated.append(
                        {
                            "node_id": target,
                            "category": category,
                            "confidence": float(seed.get("confidence") or 0),
                            "source_node": source_node,
                            "depth": depth + 1,
                            "path": next_path,
                            "evidence": [
                                "propagated through deterministic column lineage",
                                *list(seed.get("evidence") or ()),
                            ],
                        }
                    )
                queue.append((target, depth + 1, next_path))

    return {
        "status": "PASS",
        "seed_count": len(seeds),
        "propagated_count": len(propagated),
        "findings": sorted(
            propagated,
            key=lambda item: (
                item["node_id"],
                item["category"],
                item["depth"],
            ),
        ),
    }


def pii_exposure(
    graph: Mapping[str, Any],
    findings: Iterable[Mapping[str, Any]],
    *,
    terminal_resource_types: Sequence[str] = ("model", "exposure", "mart"),
) -> dict[str, Any]:
    propagated = propagate_pii(graph, findings)
    nodes = {
        str(item.get("node_id")): item
        for item in graph.get("nodes", ())
        if item.get("node_id")
    }
    terminal = {item.casefold() for item in terminal_resource_types}
    exposures = []
    for item in propagated["findings"]:
        node = nodes.get(item["node_id"], {})
        resource_type = str(node.get("resource_type") or node.get("kind") or "").casefold()
        if resource_type in terminal:
            exposures.append({**item, "node": node})
    return {
        "status": "WARN" if exposures else "PASS",
        "exposure_count": len(exposures),
        "exposures": exposures,
        "propagation": propagated,
    }


def pii_policy_check(
    sql: str,
    schema_context: Mapping[str, Mapping[str, Any]],
    *,
    allow_categories: Sequence[str] = (),
    action: str = "query",
) -> dict[str, Any]:
    query_scan = scan_query(sql, schema_context)
    allowed = {item.casefold() for item in allow_categories}
    blocked = []
    for item in query_scan.get("pii_columns_referenced", ()):
        categories = {
            str(classification.get("category") or "").casefold()
            for classification in item.get("classifications", ())
        }
        disallowed = sorted(category for category in categories if category and category not in allowed)
        if disallowed:
            blocked.append({**item, "disallowed_categories": disallowed})

    return {
        "status": "BLOCK" if blocked else "PASS",
        "action": action,
        "blocked": bool(blocked),
        "blocked_columns": blocked,
        "allow_categories": sorted(allowed),
        "reason": (
            "query references disallowed PII categories"
            if blocked
            else "no disallowed PII reference detected"
        ),
    }


def sensitive_access_report(
    rbac_graph: Mapping[str, Any],
    pii_objects: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    result = sensitive_access(rbac_graph, pii_objects)
    high = [
        item for item in result.get("findings", ())
        if str(item.get("severity") or "").upper() == "HIGH"
    ]
    return {
        **result,
        "high_severity_count": len(high),
        "summary": {
            "principals_with_sensitive_access": result.get("principal_count", 0),
            "high_severity": len(high),
        },
    }


def classify_metadata_columns(
    columns: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    findings = []
    for column in columns:
        for classification in classify_column(
            str(column.get("column_name") or column.get("name") or ""),
            data_type=str(column.get("data_type") or ""),
            description=column.get("comment") or column.get("description"),
            tags=column.get("tags") or (),
        ):
            findings.append(
                {
                    "object_id": column.get("object_id"),
                    "asset_id": column.get("asset_id"),
                    "column": column.get("column_name") or column.get("name"),
                    **classification,
                }
            )
    return {
        "status": "PASS",
        "classification_count": len(findings),
        "findings": findings,
    }
