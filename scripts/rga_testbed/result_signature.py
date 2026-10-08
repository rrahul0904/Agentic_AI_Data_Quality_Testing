"""Canonical result signatures shared by benchmark and Agent certification."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def normalize_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return format(value, ".15g")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def canonical_result(columns: list[str], rows: list[list[Any] | tuple[Any, ...]]) -> dict[str, Any]:
    normalized_columns = [str(name).upper() for name in columns]
    normalized_rows = [
        [normalize_value(value) for value in row]
        for row in rows
    ]

    paired_rows = [
        {
            normalized_columns[index]: row[index]
            for index in range(min(len(normalized_columns), len(row)))
        }
        for row in normalized_rows
    ]
    paired_rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))

    value_rows = [sorted(row, key=lambda value: "" if value is None else value) for row in normalized_rows]
    value_rows.sort(key=lambda row: json.dumps(row, separators=(",", ":")))

    strict_payload = json.dumps(
        {"columns": sorted(normalized_columns), "rows": paired_rows},
        sort_keys=True,
        separators=(",", ":"),
    )
    value_payload = json.dumps(value_rows, separators=(",", ":"))
    return {
        "columns": sorted(normalized_columns),
        "row_count": len(normalized_rows),
        "result_sha256": hashlib.sha256(strict_payload.encode()).hexdigest(),
        "value_sha256": hashlib.sha256(value_payload.encode()).hexdigest(),
    }


def result_set_signature(result_set: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(result_set, dict):
        return None
    metadata = result_set.get("resultSetMetaData")
    if not isinstance(metadata, dict):
        metadata = {}
    row_type = metadata.get("rowType")
    columns: list[str] = []
    if isinstance(row_type, list):
        for index, item in enumerate(row_type, 1):
            if isinstance(item, dict) and item.get("name"):
                columns.append(str(item["name"]))
            else:
                columns.append(f"COL_{index}")
    data = result_set.get("data")
    if not isinstance(data, list):
        return None
    if not columns and data:
        width = len(data[0]) if isinstance(data[0], (list, tuple)) else 0
        columns = [f"COL_{index}" for index in range(1, width + 1)]
    rows = [list(row) for row in data if isinstance(row, (list, tuple))]
    return canonical_result(columns, rows)


def result_set_rows(result_set: dict[str, Any], max_rows: int = 10000) -> dict[str, Any] | None:
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    if not isinstance(result_set, dict):
        return None
    metadata = result_set.get("resultSetMetaData")
    if not isinstance(metadata, dict):
        metadata = {}
    row_type = metadata.get("rowType")
    columns: list[str] = []
    if isinstance(row_type, list):
        for index, item in enumerate(row_type, 1):
            if isinstance(item, dict) and item.get("name"):
                columns.append(str(item["name"]).upper())
            else:
                columns.append(f"COL_{index}")
    data = result_set.get("data")
    if not isinstance(data, list):
        return None
    if not columns and data:
        width = len(data[0]) if isinstance(data[0], (list, tuple)) else 0
        columns = [f"COL_{index}" for index in range(1, width + 1)]

    declared_rows = metadata.get("numRows")
    try:
        declared_count = int(declared_rows) if declared_rows is not None else len(data)
    except (TypeError, ValueError):
        declared_count = len(data)
    truncated = declared_count > max_rows or len(data) > max_rows
    rows = []
    for row in data[:max_rows]:
        if not isinstance(row, (list, tuple)):
            continue
        rows.append(
            {
                columns[index]: normalize_value(value)
                for index, value in enumerate(row)
                if index < len(columns)
            }
        )
    return {
        "columns": columns,
        "rows": rows,
        "declared_row_count": declared_count,
        "captured_row_count": len(rows),
        "truncated": truncated,
    }
