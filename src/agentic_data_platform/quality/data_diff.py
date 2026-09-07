"""Deterministic source-target data diff primitives with a DuckDB local demo."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from numbers import Number
from typing import Any, Iterable, Mapping, Sequence

Row = Mapping[str, Any]


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row_hash(row: Row) -> str:
    return hashlib.sha256(_stable(dict(row)).encode("utf-8")).hexdigest()


def _key(row: Row, columns: Sequence[str]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in columns)


def infer_schema(rows: Iterable[Row]) -> dict[str, str]:
    observed: dict[str, set[str]] = {}
    for row in rows:
        for column, value in row.items():
            if value is None:
                observed.setdefault(column, set())
                continue
            if isinstance(value, bool):
                kind = "BOOLEAN"
            elif isinstance(value, int):
                kind = "INTEGER"
            elif isinstance(value, float):
                kind = "FLOAT"
            elif isinstance(value, (dict, list, tuple)):
                kind = "VARIANT"
            else:
                kind = type(value).__name__.upper()
            observed.setdefault(column, set()).add(kind)
    return {
        column: "NULL" if not kinds else next(iter(kinds)) if len(kinds) == 1 else "|".join(sorted(kinds))
        for column, kinds in sorted(observed.items())
    }


def schema_diff(source_schema: Mapping[str, str], target_schema: Mapping[str, str]) -> dict[str, Any]:
    source_columns, target_columns = set(source_schema), set(target_schema)
    common = source_columns & target_columns
    changed = [
        {"column": column, "source_type": source_schema[column], "target_type": target_schema[column]}
        for column in sorted(common)
        if source_schema[column].casefold() != target_schema[column].casefold()
    ]
    status = "PASS" if source_columns == target_columns and not changed else "FAIL"
    return {
        "status": status,
        "missing_columns": sorted(source_columns - target_columns),
        "extra_columns": sorted(target_columns - source_columns),
        "type_mismatches": changed,
        "source_columns": len(source_columns),
        "target_columns": len(target_columns),
    }


def row_count_diff(source_count: int, target_count: int, *, tolerance: int = 0) -> dict[str, Any]:
    difference = target_count - source_count
    return {
        "status": "PASS" if abs(difference) <= tolerance else "FAIL",
        "source_count": source_count,
        "target_count": target_count,
        "difference": difference,
        "tolerance": tolerance,
    }


def key_diff(source_rows: Sequence[Row], target_rows: Sequence[Row], key_columns: Sequence[str]) -> dict[str, Any]:
    source_counter = Counter(_key(row, key_columns) for row in source_rows)
    target_counter = Counter(_key(row, key_columns) for row in target_rows)
    missing = sorted(source_counter.keys() - target_counter.keys(), key=str)
    extra = sorted(target_counter.keys() - source_counter.keys(), key=str)
    source_duplicates = [key for key, count in source_counter.items() if count > 1]
    target_duplicates = [key for key, count in target_counter.items() if count > 1]
    status = "PASS" if not (missing or extra or source_duplicates or target_duplicates) else "FAIL"
    return {
        "status": status,
        "key_columns": list(key_columns),
        "missing_keys": [list(item) for item in missing],
        "extra_keys": [list(item) for item in extra],
        "source_duplicate_keys": [list(item) for item in sorted(source_duplicates, key=str)],
        "target_duplicate_keys": [list(item) for item in sorted(target_duplicates, key=str)],
    }


def row_diff(
    source_rows: Sequence[Row],
    target_rows: Sequence[Row],
    key_columns: Sequence[str],
    *,
    compare_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    source = {_key(row, key_columns): dict(row) for row in source_rows}
    target = {_key(row, key_columns): dict(row) for row in target_rows}
    source_keys, target_keys = set(source), set(target)
    missing = source_keys - target_keys
    extra = target_keys - source_keys
    changed: list[dict[str, Any]] = []
    matches = 0

    for key in sorted(source_keys & target_keys, key=str):
        left, right = source[key], target[key]
        columns = list(compare_columns) if compare_columns else sorted((set(left) | set(right)) - set(key_columns))
        differences = {
            column: {"source": left.get(column), "target": right.get(column)}
            for column in columns
            if left.get(column) != right.get(column)
        }
        if differences:
            changed.append({"key": list(key), "columns": differences})
        else:
            matches += 1

    status = "PASS" if not (missing or extra or changed) else "FAIL"
    return {
        "status": status,
        "key_columns": list(key_columns),
        "matches": matches,
        "missing_rows": [source[key] for key in sorted(missing, key=str)],
        "extra_rows": [target[key] for key in sorted(extra, key=str)],
        "changed_rows": changed,
        "counts": {
            "matches": matches,
            "missing": len(missing),
            "extra": len(extra),
            "changed": len(changed),
        },
    }


def hash_diff(source_rows: Sequence[Row], target_rows: Sequence[Row], key_columns: Sequence[str]) -> dict[str, Any]:
    source = {_key(row, key_columns): _row_hash(row) for row in source_rows}
    target = {_key(row, key_columns): _row_hash(row) for row in target_rows}
    shared = set(source) & set(target)
    changed = [list(key) for key in sorted(shared, key=str) if source[key] != target[key]]
    missing = [list(key) for key in sorted(set(source) - set(target), key=str)]
    extra = [list(key) for key in sorted(set(target) - set(source), key=str)]
    return {
        "status": "PASS" if not (changed or missing or extra) else "FAIL",
        "algorithm": "sha256-json-canonical",
        "changed_keys": changed,
        "missing_keys": missing,
        "extra_keys": extra,
    }


def aggregate_diff(
    source_rows: Sequence[Row],
    target_rows: Sequence[Row],
    column: str,
    *,
    aggregate: str = "sum",
    tolerance: float = 0.0,
) -> dict[str, Any]:
    def values(rows: Sequence[Row]) -> list[Number]:
        return [row[column] for row in rows if isinstance(row.get(column), Number) and not isinstance(row.get(column), bool)]

    def calculate(items: list[Number]) -> float:
        if aggregate == "sum":
            return float(sum(items))
        if aggregate == "min":
            return float(min(items)) if items else 0.0
        if aggregate == "max":
            return float(max(items)) if items else 0.0
        if aggregate == "avg":
            return float(sum(items) / len(items)) if items else 0.0
        if aggregate == "count":
            return float(len(items))
        raise ValueError(f"unsupported aggregate: {aggregate}")

    source_value, target_value = calculate(values(source_rows)), calculate(values(target_rows))
    difference = target_value - source_value
    return {
        "status": "PASS" if abs(difference) <= tolerance else "FAIL",
        "column": column,
        "aggregate": aggregate,
        "source_value": source_value,
        "target_value": target_value,
        "difference": difference,
        "tolerance": tolerance,
    }


def data_diff_report(
    source_rows: Sequence[Row],
    target_rows: Sequence[Row],
    key_columns: Sequence[str],
    *,
    aggregate_columns: Sequence[str] = (),
) -> dict[str, Any]:
    source_schema, target_schema = infer_schema(source_rows), infer_schema(target_rows)
    rows = row_diff(source_rows, target_rows, key_columns)
    report = {
        "mode": "LOCAL_SIMULATION",
        "schema": schema_diff(source_schema, target_schema),
        "row_count": row_count_diff(len(source_rows), len(target_rows)),
        "keys": key_diff(source_rows, target_rows, key_columns),
        "hash": hash_diff(source_rows, target_rows, key_columns),
        "rows": rows,
        "aggregates": [
            aggregate_diff(source_rows, target_rows, column, aggregate="sum") for column in aggregate_columns
        ],
    }
    statuses = [report["schema"]["status"], report["row_count"]["status"], report["keys"]["status"], report["hash"]["status"]]
    statuses.extend(item["status"] for item in report["aggregates"])
    report["status"] = "PASS" if all(status == "PASS" for status in statuses) else "FAIL"
    return report


def duckdb_demo_diff() -> dict[str, Any]:
    """Execute a real local DuckDB source/target fixture and diff the fetched rows."""

    import duckdb

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE source_orders(id INTEGER, guest_id INTEGER, amount DOUBLE, status VARCHAR)")
        connection.execute("CREATE TABLE target_orders(id INTEGER, guest_id INTEGER, amount DOUBLE, status VARCHAR)")
        connection.execute(
            "INSERT INTO source_orders VALUES (1, 10, 120.0, 'CONFIRMED'), (2, 20, 90.0, 'CONFIRMED'), "
            "(3, 30, 45.0, 'CANCELLED')"
        )
        connection.execute(
            "INSERT INTO target_orders VALUES (1, 10, 120.0, 'CONFIRMED'), (2, 20, 95.0, 'CONFIRMED'), "
            "(4, 40, 60.0, 'CONFIRMED')"
        )

        def fetch(table: str) -> list[dict[str, Any]]:
            cursor = connection.execute(f"SELECT * FROM {table} ORDER BY id")
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

        report = data_diff_report(fetch("source_orders"), fetch("target_orders"), ["id"], aggregate_columns=["amount"])
        report["source"] = "duckdb:source_orders"
        report["target"] = "duckdb:target_orders"
        return report
    finally:
        connection.close()
