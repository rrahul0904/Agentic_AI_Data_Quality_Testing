"""Warehouse RBAC graph and sensitive-access analysis."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable, Mapping

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability


def _value(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    lookup = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in lookup:
            return lookup[name.casefold()]
    return default


def build_rbac_graph(metadata: Mapping[str, Any]) -> dict[str, Any]:
    roles = metadata.get("roles", ())
    role_grants = metadata.get("role_grants", ())
    user_grants = metadata.get("user_grants", ())
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(kind: str, name: str) -> str:
        node_id = f"{kind}:{name}"
        nodes.setdefault(node_id, {"node_id": node_id, "kind": kind, "name": name})
        return node_id

    for row in roles:
        name = _value(row, "name", "role", "grantee_name")
        if name:
            add_node("role", str(name))

    for row in role_grants:
        grantee = _value(row, "grantee_name", "grantee", "role")
        granted_on = _value(row, "granted_on", "grant_on")
        name = _value(row, "name", "object_name")
        privilege = _value(row, "privilege")
        granted_role = _value(row, "role", "granted_role")

        if granted_role and grantee:
            source = add_node("role", str(grantee))
            target = add_node("role", str(granted_role))
            edges.append({"source": source, "target": target, "kind": "inherits_role"})
            continue
        if grantee and name:
            source = add_node("role", str(grantee))
            kind = str(granted_on or "object").casefold().replace(" ", "_")
            target = add_node(kind, str(name))
            edges.append({
                "source": source,
                "target": target,
                "kind": "granted",
                "privilege": str(privilege or ""),
                "grant_option": _value(row, "grant_option", "grantable"),
            })

    for row in user_grants:
        user = _value(row, "grantee_name", "grantee", "name", "user_name")
        role = _value(row, "role", "granted_role")
        if user and role:
            source = add_node("user", str(user))
            target = add_node("role", str(role))
            edges.append({"source": source, "target": target, "kind": "has_role"})

    return {
        "nodes": sorted(nodes.values(), key=lambda item: item["node_id"]),
        "edges": edges,
        "counts": {
            "users": sum(item["kind"] == "user" for item in nodes.values()),
            "roles": sum(item["kind"] == "role" for item in nodes.values()),
            "objects": sum(item["kind"] not in {"user", "role"} for item in nodes.values()),
        },
    }


def rbac_inventory(connector: DataPlatformConnector) -> dict[str, Any]:
    if not connector.supports(ConnectorCapability.GET_ROLE_METADATA):
        return {
            "status": "UNSUPPORTED",
            "platform": connector.platform,
            "graph": {"nodes": [], "edges": [], "counts": {}},
        }
    metadata = connector.role_metadata()
    return {
        "status": "PASS",
        "platform": connector.platform,
        "graph": build_rbac_graph(metadata),
        "raw_counts": {key: len(value) for key, value in metadata.items() if isinstance(value, list)},
    }


def _adjacency(graph: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", ()):
        result[str(edge["source"])].append(dict(edge))
    return result


def reachable_access(graph: Mapping[str, Any], principal_kind: str, principal: str) -> dict[str, Any]:
    start = f"{principal_kind}:{principal}"
    nodes = {str(item["node_id"]): item for item in graph.get("nodes", ())}
    if start not in nodes:
        raise KeyError(f"RBAC principal not found: {start}")
    adjacency = _adjacency(graph)
    queue = deque([(start, [])])
    seen = {start}
    access = []
    roles = []
    while queue:
        current, path = queue.popleft()
        for edge in adjacency.get(current, ()):
            target = str(edge["target"])
            if target in seen:
                continue
            seen.add(target)
            target_node = nodes.get(target, {"node_id": target, "kind": target.split(":", 1)[0], "name": target.split(":", 1)[-1]})
            entry = {
                "node": target_node,
                "via": [*path, edge],
            }
            if target_node["kind"] == "role":
                roles.append(entry)
                queue.append((target, [*path, edge]))
            else:
                access.append(entry)
    return {
        "principal": start,
        "roles": roles,
        "access": access,
        "access_count": len(access),
    }


def object_access(graph: Mapping[str, Any], object_name: str) -> dict[str, Any]:
    wanted = object_name.casefold()
    principals = []
    for node in graph.get("nodes", ()):
        if node.get("kind") not in {"user", "role"}:
            continue
        try:
            access = reachable_access(graph, str(node["kind"]), str(node["name"]))
        except KeyError:
            continue
        matches = [
            item for item in access["access"]
            if str(item["node"].get("name", "")).casefold() == wanted
        ]
        if matches:
            principals.append({"principal": node, "access": matches})
    return {"object": object_name, "principals": principals, "count": len(principals)}


def sensitive_access(
    graph: Mapping[str, Any],
    sensitive_objects: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sensitive_objects:
        object_name = str(item.get("object_name") or item.get("asset") or item.get("object_id") or "")
        if object_name:
            by_object[object_name.casefold()].append(dict(item))

    findings = []
    for node in graph.get("nodes", ()):
        if node.get("kind") not in {"user", "role"}:
            continue
        access = reachable_access(graph, str(node["kind"]), str(node["name"]))
        exposed = []
        for item in access["access"]:
            object_name = str(item["node"].get("name") or "")
            matched = by_object.get(object_name.casefold(), [])
            if matched:
                exposed.append({
                    "object": object_name,
                    "sensitive_columns": matched,
                    "path": item["via"],
                })
        if exposed:
            findings.append({
                "principal": node,
                "sensitive_object_count": len(exposed),
                "exposures": exposed,
                "severity": "HIGH" if len(exposed) >= 10 else "MEDIUM",
            })
    return {
        "status": "WARN" if findings else "PASS",
        "findings": findings,
        "principal_count": len(findings),
    }


def excessive_privileges(
    graph: Mapping[str, Any],
    *,
    observed_objects_by_principal: Mapping[str, Iterable[str]] | None = None,
    minimum_grants: int = 20,
    unused_ratio_threshold: float = 0.8,
) -> dict[str, Any]:
    observed = {
        key.casefold(): {str(item).casefold() for item in values}
        for key, values in (observed_objects_by_principal or {}).items()
    }
    findings = []
    for node in graph.get("nodes", ()):
        if node.get("kind") not in {"user", "role"}:
            continue
        principal_id = str(node["node_id"])
        access = reachable_access(graph, str(node["kind"]), str(node["name"]))
        granted = {
            str(item["node"].get("name") or "").casefold()
            for item in access["access"]
            if item["node"].get("name")
        }
        if len(granted) < minimum_grants:
            continue
        used = observed.get(principal_id.casefold(), set())
        unused = granted - used
        ratio = len(unused) / len(granted) if granted else 0
        if ratio >= unused_ratio_threshold:
            findings.append({
                "principal": node,
                "granted_objects": len(granted),
                "observed_objects": len(granted & used),
                "unused_objects": len(unused),
                "unused_ratio": ratio,
                "severity": "HIGH" if ratio >= 0.95 else "MEDIUM",
            })
    return {"status": "WARN" if findings else "PASS", "findings": findings}
