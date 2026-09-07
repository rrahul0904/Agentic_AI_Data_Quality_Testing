"""Common quality result creation and fail-closed batch quality gate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .audit import execution_mode, persist_quality_results


def _result(
    *,
    batch_id: str,
    check_id: str,
    asset: str,
    check_type: str,
    status: str,
    observed_value: Any,
    expected_value: Any,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "result_id": uuid.uuid4().hex,
        "check_id": check_id,
        "batch_id": batch_id,
        "system": execution_mode(),
        "layer": "RAW",
        "asset": asset,
        "check_type": check_type,
        "severity": "ERROR",
        "status": status,
        "observed_value": observed_value,
        "expected_value": expected_value,
        "details": details or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }


def quality_gate(ti: Any, **_: Any) -> dict[str, Any]:
    copy_result = ti.xcom_pull(task_ids="copy_raw")
    reconciliation = ti.xcom_pull(task_ids="reconcile")
    target_rows = copy_result["target_row_count"]
    results = [
        _result(
            batch_id=copy_result["batch_id"],
            check_id="raw_batch_nonempty",
            asset=copy_result["loads"][0]["target_object"] if copy_result["loads"] else "RAW",
            check_type="row_count",
            status="PASS" if target_rows > 0 else "FAIL",
            observed_value=target_rows,
            expected_value={"minimum": 1},
        )
    ]
    for row in reconciliation["results"]:
        results.append(
            _result(
                batch_id=copy_result["batch_id"],
                check_id=f"{row['entity']}_row_count_reconciliation",
                asset=row["entity"],
                check_type="row_count_reconciliation",
                status=row["status"],
                observed_value={"source": row["source_value"], "target": row["target_value"]},
                expected_value={
                    "absolute_tolerance": row["absolute_tolerance"],
                    "percentage_tolerance": row["percentage_tolerance"],
                },
                details={"difference": row["difference"], "difference_pct": row["difference_pct"]},
            )
        )
    persist_quality_results(results)
    failed = [result for result in results if result["status"] != "PASS"]
    if failed:
        raise ValueError(f"Quality gate failed for {len(failed)} check(s) in batch {copy_result['batch_id']}")
    return {"batch_id": copy_result["batch_id"], "status": "PASS", "results": results}
