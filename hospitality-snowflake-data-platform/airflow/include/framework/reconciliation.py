"""Deterministic source/target count reconciliation."""

from __future__ import annotations

import os
from typing import Any


def compare_counts(
    source_value: int,
    target_value: int,
    *,
    absolute_tolerance: float = 0,
    percentage_tolerance: float = 0,
) -> dict[str, Any]:
    difference = abs(source_value - target_value)
    difference_pct = (difference / source_value * 100.0) if source_value else (0.0 if target_value == 0 else 100.0)
    within_absolute = difference <= absolute_tolerance
    within_percentage = difference_pct <= percentage_tolerance
    return {
        "metric": "row_count",
        "source_value": source_value,
        "target_value": target_value,
        "difference": difference,
        "difference_pct": round(difference_pct, 8),
        "absolute_tolerance": absolute_tolerance,
        "percentage_tolerance": percentage_tolerance,
        "status": "PASS" if within_absolute or within_percentage else "FAIL",
    }


def reconcile(ti: Any, **_: Any) -> dict[str, Any]:
    copy_result = ti.xcom_pull(task_ids="copy_raw")
    absolute = float(os.environ.get("RECONCILIATION_ABSOLUTE_TOLERANCE", "0"))
    percentage = float(os.environ.get("RECONCILIATION_PERCENTAGE_TOLERANCE", "0"))
    results = []
    for load in copy_result["loads"]:
        result = compare_counts(
            load["source_row_count"],
            load["target_row_count"],
            absolute_tolerance=absolute,
            percentage_tolerance=percentage,
        )
        results.append({"entity": load["entity"], **result})
    return {
        "batch_id": copy_result["batch_id"],
        "status": "PASS" if all(result["status"] == "PASS" for result in results) else "FAIL",
        "results": results,
    }
