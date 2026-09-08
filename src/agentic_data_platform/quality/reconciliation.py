"""Generic, tolerance-aware source/target reconciliation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping, Sequence


def _numeric_result(
    metric: str,
    source_value: float,
    target_value: float,
    *,
    absolute_tolerance: float = 0,
    percentage_tolerance: float = 0,
    source: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if absolute_tolerance < 0 or percentage_tolerance < 0:
        raise ValueError("tolerances must be non-negative")
    difference = abs(source_value - target_value)
    denominator = abs(source_value)
    difference_pct = (difference / denominator * 100) if denominator else (0.0 if difference == 0 else 100.0)
    allowed = difference <= absolute_tolerance or difference_pct <= percentage_tolerance
    return {
        "source": source or {}, "target": target or {}, "metric": metric,
        "source_value": source_value, "target_value": target_value,
        "difference": difference, "difference_pct": difference_pct,
        "tolerance": {"absolute": absolute_tolerance, "percentage": percentage_tolerance},
        "status": "PASS" if allowed else "FAIL",
    }


def reconcile_row_count(source_value: int, target_value: int, **kwargs: Any) -> dict[str, Any]:
    return _numeric_result("row_count", source_value, target_value, **kwargs)


def reconcile_aggregate(source_value: float, target_value: float, *, aggregate: str = "sum", **kwargs: Any) -> dict[str, Any]:
    result = _numeric_result("aggregate", source_value, target_value, **kwargs)
    result["aggregate"] = aggregate
    return result


def reconcile_nulls(source_nulls: int, target_nulls: int, **kwargs: Any) -> dict[str, Any]:
    return _numeric_result("null_count", source_nulls, target_nulls, **kwargs)


def reconcile_duplicates(source_duplicates: int, target_duplicates: int, **kwargs: Any) -> dict[str, Any]:
    return _numeric_result("duplicate_count", source_duplicates, target_duplicates, **kwargs)


def reconcile_primary_keys(source_keys: Iterable[Any], target_keys: Iterable[Any]) -> dict[str, Any]:
    source = set(source_keys)
    target = set(target_keys)
    missing_target = sorted(source - target, key=str)
    missing_source = sorted(target - source, key=str)
    return {
        "source": {}, "target": {}, "metric": "primary_keys", "source_value": len(source),
        "target_value": len(target), "difference": len(missing_target) + len(missing_source),
        "missing_in_target": missing_target, "missing_in_source": missing_source,
        "status": "PASS" if not missing_target and not missing_source else "FAIL",
    }


def _timestamp(value: str | datetime) -> datetime:
    item = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return item if item.tzinfo else item.replace(tzinfo=timezone.utc)


def reconcile_freshness(
    source_timestamp: str | datetime,
    target_timestamp: str | datetime,
    *,
    tolerance_seconds: float = 0,
) -> dict[str, Any]:
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be non-negative")
    source = _timestamp(source_timestamp)
    target = _timestamp(target_timestamp)
    lag = max(0.0, (source - target).total_seconds())
    return {
        "source": {}, "target": {}, "metric": "freshness", "source_value": source.isoformat(),
        "target_value": target.isoformat(), "difference_seconds": lag,
        "tolerance": {"seconds": tolerance_seconds}, "status": "PASS" if lag <= tolerance_seconds else "FAIL",
    }


def canonical_value(value: Any) -> Any:
    """Normalize cross-warehouse primitive values before hashing.

    The representation is deterministic for NULLs, decimals, floats, booleans,
    timestamps/dates, strings, mappings and nested sequences.
    """
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return {"type": "decimal", "value": format(normalized, "f")}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        if math.isnan(value):
            rendered = "NaN"
        elif math.isinf(value):
            rendered = "Infinity" if value > 0 else "-Infinity"
        else:
            rendered = format(value, ".17g")
        return {"type": "float", "value": rendered}
    if isinstance(value, datetime):
        item = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return {"type": "timestamp", "value": item.astimezone(timezone.utc).isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "value": {
                str(key): canonical_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            },
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {"type": "array", "value": [canonical_value(item) for item in value]}
    return {"type": "string", "value": str(value)}


def canonical_row(
    row: Mapping[str, Any],
    *,
    columns: Sequence[str] | None = None,
) -> str:
    selected = list(columns) if columns is not None else sorted(str(key) for key in row)
    payload = {column: canonical_value(row.get(column)) for column in selected}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def row_hash(
    row: Mapping[str, Any],
    *,
    columns: Sequence[str] | None = None,
) -> str:
    return sha256(canonical_row(row, columns=columns).encode("utf-8")).hexdigest()


def dataset_hash(
    rows: Iterable[Mapping[str, Any]],
    *,
    columns: Sequence[str] | None = None,
    order_independent: bool = True,
) -> dict[str, Any]:
    hashes = [row_hash(row, columns=columns) for row in rows]
    if order_independent:
        hashes.sort()
    digest = sha256("\n".join(hashes).encode("ascii")).hexdigest()
    return {
        "row_count": len(hashes),
        "hash": digest,
        "row_hashes": hashes,
        "order_independent": order_independent,
    }


def reconcile_hash(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
    *,
    columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    source = dataset_hash(source_rows, columns=columns)
    target = dataset_hash(target_rows, columns=columns)
    return {
        "metric": "dataset_hash",
        "source_value": source["hash"],
        "target_value": target["hash"],
        "source_count": source["row_count"],
        "target_count": target["row_count"],
        "columns": list(columns) if columns is not None else None,
        "status": "PASS" if source["hash"] == target["hash"] and source["row_count"] == target["row_count"] else "FAIL",
    }


def _bucket_index(key: Any, bucket_count: int) -> int:
    if bucket_count < 1:
        raise ValueError("bucket_count must be at least 1")
    digest = sha256(json.dumps(canonical_value(key), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % bucket_count


def bucket_hashes(
    rows: Iterable[Mapping[str, Any]],
    *,
    key_column: str,
    bucket_count: int = 64,
    columns: Sequence[str] | None = None,
) -> dict[int, dict[str, Any]]:
    buckets: dict[int, list[Mapping[str, Any]]] = {index: [] for index in range(bucket_count)}
    for row in rows:
        buckets[_bucket_index(row.get(key_column), bucket_count)].append(row)
    return {
        index: {
            "row_count": result["row_count"],
            "hash": result["hash"],
        }
        for index, values in buckets.items()
        if values
        for result in [dataset_hash(values, columns=columns)]
    }


def reconcile_bucket_hash(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
    *,
    key_column: str,
    bucket_count: int = 64,
    columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    source = bucket_hashes(source_rows, key_column=key_column, bucket_count=bucket_count, columns=columns)
    target = bucket_hashes(target_rows, key_column=key_column, bucket_count=bucket_count, columns=columns)
    all_buckets = sorted(set(source) | set(target))
    mismatches = []
    for bucket in all_buckets:
        source_value = source.get(bucket, {"row_count": 0, "hash": None})
        target_value = target.get(bucket, {"row_count": 0, "hash": None})
        if source_value != target_value:
            mismatches.append({
                "bucket": bucket,
                "source": source_value,
                "target": target_value,
            })
    return {
        "metric": "bucket_hash",
        "key_column": key_column,
        "bucket_count": bucket_count,
        "source_bucket_count": len(source),
        "target_bucket_count": len(target),
        "mismatch_count": len(mismatches),
        "mismatched_buckets": mismatches,
        "status": "PASS" if not mismatches else "FAIL",
    }
