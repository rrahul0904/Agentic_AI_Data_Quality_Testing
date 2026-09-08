"""Evidence-backed warehouse FinOps analytics and deterministic advisor."""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability


def _value(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    lookup = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in lookup:
            return lookup[name.casefold()]
    return default


def query_history(connector: DataPlatformConnector, **kwargs: Any) -> dict[str, Any]:
    if not connector.supports(ConnectorCapability.GET_QUERY_HISTORY):
        return {
            "status": "UNSUPPORTED",
            "platform": connector.platform,
            "queries": [],
            "reason": "connector does not advertise query-history capability",
        }
    rows = connector.query_history(**kwargs)
    normalized = []
    for row in rows:
        normalized.append({
            "query_id": _value(row, "query_id", "job_id", "statement_id", "query"),
            "query_text": _value(row, "query_text", "query", "querytxt", default=""),
            "query_type": _value(row, "query_type", "statement_type"),
            "warehouse": _value(row, "warehouse_name", "warehouse_id"),
            "warehouse_size": _value(row, "warehouse_size"),
            "user": _value(row, "user_name", "user", "user_email", "executed_by"),
            "role": _value(row, "role_name", "role"),
            "database": _value(row, "database_name", "database"),
            "schema": _value(row, "schema_name", "schema"),
            "status": _value(row, "execution_status", "state"),
            "error_code": _value(row, "error_code"),
            "error_message": _value(row, "error_message", "error_result"),
            "elapsed_ms": _value(row, "total_elapsed_time", "query_duration_ms", "total_duration_ms"),
            "execution_ms": _value(row, "execution_time"),
            "queued_ms": (
                float(_value(row, "queued_overload_time", default=0) or 0)
                + float(_value(row, "queued_provisioning_time", default=0) or 0)
            ),
            "bytes_scanned": _value(row, "bytes_scanned", "total_bytes_processed", "read_bytes"),
            "bytes_spilled_local": _value(row, "bytes_spilled_to_local_storage", default=0),
            "bytes_spilled_remote": _value(row, "bytes_spilled_to_remote_storage", default=0),
            "rows": _value(row, "rows_produced", "result_rows", "rows"),
            "start_time": _value(row, "start_time", "creation_time"),
            "end_time": _value(row, "end_time"),
            "raw": row,
        })
    return {
        "status": "PASS",
        "platform": connector.platform,
        "count": len(normalized),
        "queries": normalized,
    }


def expensive_queries(
    history: Iterable[dict[str, Any]],
    *,
    limit: int = 25,
    min_elapsed_ms: float | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for query in history:
        elapsed = float(query.get("elapsed_ms") or 0)
        if min_elapsed_ms is not None and elapsed < min_elapsed_ms:
            continue
        bytes_scanned = float(query.get("bytes_scanned") or 0)
        spill = float(query.get("bytes_spilled_local") or 0) + float(query.get("bytes_spilled_remote") or 0)
        queue = float(query.get("queued_ms") or 0)
        score = elapsed + (bytes_scanned / 1024**2) + (spill / 1024**2) * 2 + queue * 1.5
        rows.append({**query, "expense_score": score})
    return sorted(rows, key=lambda item: item["expense_score"], reverse=True)[: max(1, limit)]


def query_errors(history: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        query for query in history
        if query.get("error_code")
        or query.get("error_message")
        or str(query.get("status") or "").casefold() in {"failed", "fail", "error"}
    ]


def query_patterns(history: Iterable[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    def fingerprint(sql: str) -> str:
        value = re.sub(r"'(?:''|[^'])*'", "?", sql)
        value = re.sub(r"\b\d+(?:\.\d+)?\b", "?", value)
        value = re.sub(r"\s+", " ", value).strip().casefold()
        return value[:1000]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in history:
        sql = str(query.get("query_text") or "")
        if sql:
            groups[fingerprint(sql)].append(query)
    result = []
    for pattern, queries in groups.items():
        elapsed = [float(item.get("elapsed_ms") or 0) for item in queries]
        bytes_scanned = [float(item.get("bytes_scanned") or 0) for item in queries]
        result.append({
            "pattern": pattern,
            "count": len(queries),
            "total_elapsed_ms": sum(elapsed),
            "median_elapsed_ms": median(elapsed) if elapsed else 0,
            "total_bytes_scanned": sum(bytes_scanned),
            "users": sorted({str(item.get("user")) for item in queries if item.get("user")}),
        })
    return sorted(result, key=lambda item: (item["total_elapsed_ms"], item["count"]), reverse=True)[:limit]


def cost_summary(connector: DataPlatformConnector, **kwargs: Any) -> dict[str, Any]:
    if not connector.supports(ConnectorCapability.GET_COST_METADATA):
        return {
            "status": "UNSUPPORTED",
            "platform": connector.platform,
            "reason": "connector does not advertise cost metadata",
        }
    result = connector.cost_usage(**kwargs)
    return {"status": "PASS", "platform": connector.platform, **result}


def warehouse_usage(connector: DataPlatformConnector, **kwargs: Any) -> dict[str, Any]:
    try:
        result = connector.warehouse_usage(**kwargs)
    except NotImplementedError:
        return {
            "status": "UNSUPPORTED",
            "platform": connector.platform,
            "reason": "connector does not expose warehouse-load metadata",
        }
    return {"status": "PASS", "platform": connector.platform, **result}


def _warehouse_row(rows: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    wanted = name.casefold()
    for row in rows:
        value = _value(row, "warehouse_name", "name")
        if value is not None and str(value).casefold() == wanted:
            return row
    return None


def warehouse_advisor(connector: DataPlatformConnector, *, days: int = 7) -> dict[str, Any]:
    usage = warehouse_usage(connector, days=days)
    if usage.get("status") != "PASS":
        return {
            "status": "UNSUPPORTED",
            "platform": connector.platform,
            "recommendations": [],
            "reason": usage.get("reason"),
        }

    metering = usage.get("metering", [])
    load = usage.get("load", [])
    warehouse_rows = usage.get("warehouses", [])
    names = sorted({
        str(_value(row, "warehouse_name", "name"))
        for collection in (metering, load, warehouse_rows)
        for row in collection
        if _value(row, "warehouse_name", "name") is not None
    })
    recommendations = []
    for name in names:
        meter = _warehouse_row(metering, name) or {}
        load_row = _warehouse_row(load, name) or {}
        definition = _warehouse_row(warehouse_rows, name) or {}
        credits = float(_value(meter, "credits_used", default=0) or 0)
        avg_running = float(_value(load_row, "avg_running", default=0) or 0)
        peak_running = float(_value(load_row, "peak_running", default=0) or 0)
        avg_queue = float(_value(load_row, "avg_queued_load", default=0) or 0)
        peak_queue = float(_value(load_row, "peak_queued_load", default=0) or 0)
        size = str(_value(definition, "size", "warehouse_size", default="UNKNOWN"))
        state = str(_value(definition, "state", default="UNKNOWN"))
        evidence = {
            "days": days,
            "credits_used": credits,
            "avg_running": avg_running,
            "peak_running": peak_running,
            "avg_queued_load": avg_queue,
            "peak_queued_load": peak_queue,
            "size": size,
            "state": state,
        }

        if not meter and not load_row:
            action, confidence, reason = "REVIEW", "low", "insufficient usage/load history"
        elif credits == 0 and avg_running == 0 and peak_running == 0:
            action, confidence, reason = "SUSPEND", "high", "no measured compute consumption or running load"
        elif peak_queue >= 2 or avg_queue >= 0.5:
            action, confidence, reason = "SCALE_UP", "high", "sustained or peak queue pressure"
        elif peak_running >= 8 and avg_queue > 0:
            action, confidence, reason = "ENABLE_MULTI_CLUSTER", "medium", "high concurrency with queueing"
        elif credits > 0 and avg_running < 0.25 and peak_queue == 0:
            action, confidence, reason = "SCALE_DOWN", "medium", "low concurrency with no queue pressure"
        else:
            action, confidence, reason = "HEALTHY", "medium", "available evidence shows no strong sizing pressure"

        recommendations.append({
            "warehouse": name,
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "evidence": evidence,
        })

    return {
        "status": "PASS",
        "platform": connector.platform,
        "days": days,
        "recommendations": recommendations,
    }


def idle_resources(connector: DataPlatformConnector, *, days: int = 7) -> dict[str, Any]:
    advisor = warehouse_advisor(connector, days=days)
    return {
        "status": advisor.get("status"),
        "platform": connector.platform,
        "resources": [
            item for item in advisor.get("recommendations", ())
            if item["action"] in {"SUSPEND", "DELETE_UNUSED"}
        ],
    }


def full_finops_report(connector: DataPlatformConnector, *, days: int = 7, limit: int = 1000, **kwargs: Any) -> dict[str, Any]:
    history_result = query_history(connector, days=days, limit=limit, **kwargs)
    history = history_result.get("queries", [])
    cost = cost_summary(connector, days=days, **kwargs)
    advisor = warehouse_advisor(connector, days=days)
    return {
        "platform": connector.platform,
        "query_history": history_result,
        "expensive_queries": expensive_queries(history),
        "query_errors": query_errors(history),
        "query_patterns": query_patterns(history),
        "cost_summary": cost,
        "warehouse_advisor": advisor,
        "idle_resources": idle_resources(connector, days=days),
        "status": "PASS" if history_result.get("status") == "PASS" else history_result.get("status"),
    }
