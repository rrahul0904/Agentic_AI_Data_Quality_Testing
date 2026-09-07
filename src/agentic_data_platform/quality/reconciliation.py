"""Generic, tolerance-aware source/target reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


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
