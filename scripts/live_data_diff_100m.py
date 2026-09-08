#!/usr/bin/env python3
"""External 100M+ Data Diff certification; fail/skip closed and read-only."""

from __future__ import annotations

import json
import os
import platform
import resource
import signal
import time
from contextlib import contextmanager
from typing import Any, Iterator

from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args
from agentic_data_platform.quality.warehouse_diff import WarehouseDiffEngine
from agentic_data_platform.security.redaction import redact_string


MIN_ROWS = 100_000_000


def _count(connector: Any, table: str) -> int:
    rows = connector.execute_read(f"SELECT COUNT(*) AS row_count FROM {table}").rows
    return int(rows[0].get("row_count") or rows[0].get("ROW_COUNT") or 0)


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return value / (1024 * 1024)
    return value / 1024


def _skip(reason: str) -> int:
    print(json.dumps({"status": "SKIP_EXTERNAL", "reason": reason, "minimum_rows": MIN_ROWS}, indent=2))
    return 0


def _expected_diff() -> dict[str, Any] | None:
    required = {
        "status": os.getenv("ADE_DATA_DIFF_EXPECT_STATUS"),
        "changed": os.getenv("ADE_DATA_DIFF_EXPECT_CHANGED_KEYS"),
        "missing": os.getenv("ADE_DATA_DIFF_EXPECT_MISSING_KEYS"),
        "extra": os.getenv("ADE_DATA_DIFF_EXPECT_EXTRA_KEYS"),
    }
    if any(value is None or value == "" for value in required.values()):
        return None
    status = str(required["status"]).upper()
    if status not in {"PASS", "FAIL"}:
        raise ValueError("ADE_DATA_DIFF_EXPECT_STATUS must be PASS or FAIL")
    counts = {name: int(required[name]) for name in ("changed", "missing", "extra")}
    if any(value < 0 for value in counts.values()):
        raise ValueError("expected diff key counts must be non-negative")
    return {"status": status, **counts}


def _validate_result(result: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    actual = {
        "status": str(result.get("status") or ""),
        "changed": len(result.get("changed_keys") or ()),
        "missing": len(result.get("missing_keys") or ()),
        "extra": len(result.get("extra_keys") or ()),
    }
    matched = actual == expected
    no_raw_egress = int(result.get("raw_rows_retrieved", 0) or 0) == 0
    pushdown = bool(result.get("warehouse_pushdown"))
    return matched and no_raw_egress and pushdown, {
        "expected": expected,
        "actual": actual,
        "expected_match": matched,
        "zero_raw_rows_transferred": no_raw_egress,
        "warehouse_pushdown": pushdown,
    }


class _ExecutionTimeout(TimeoutError):
    pass


@contextmanager
def _deadline(seconds: int) -> Iterator[None]:
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def handler(signum: int, frame: Any) -> None:
        raise _ExecutionTimeout(f"Data Diff exceeded timeout_seconds={seconds}")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def main() -> int:
    source_platform = os.getenv("ADE_DATA_DIFF_SOURCE_PLATFORM")
    target_platform = os.getenv("ADE_DATA_DIFF_TARGET_PLATFORM") or source_platform
    source_table = os.getenv("ADE_DATA_DIFF_SOURCE_TABLE")
    target_table = os.getenv("ADE_DATA_DIFF_TARGET_TABLE")
    keys = tuple(item.strip() for item in os.getenv("ADE_DATA_DIFF_KEYS", "").split(",") if item.strip())
    compare = tuple(item.strip() for item in os.getenv("ADE_DATA_DIFF_COMPARE_COLUMNS", "").split(",") if item.strip()) or None
    max_partition_rows = int(os.getenv("ADE_DATA_DIFF_MAX_PARTITION_ROWS", "50000"))
    detail_limit = int(os.getenv("ADE_DATA_DIFF_DETAIL_LIMIT", "100"))
    timeout_seconds = int(os.getenv("ADE_DATA_DIFF_TIMEOUT_SECONDS", "3600"))

    if not source_platform or not target_platform:
        return _skip("ADE_DATA_DIFF_SOURCE_PLATFORM and target platform are not configured")
    if not source_table or not target_table or not keys:
        return _skip("ADE_DATA_DIFF_SOURCE_TABLE, ADE_DATA_DIFF_TARGET_TABLE and ADE_DATA_DIFF_KEYS are required")

    try:
        expected = _expected_diff()
    except (TypeError, ValueError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "stage": "expectation_config",
            "reason": redact_string(str(exc)),
        }, indent=2))
        return 1
    if expected is None:
        print(json.dumps({
            "status": "NOT_RUN_EXPECTATION_UNCONFIGURED",
            "reason": "100M+ certification requires explicit expected diff status and changed/missing/extra key counts",
            "required": [
                "ADE_DATA_DIFF_EXPECT_STATUS",
                "ADE_DATA_DIFF_EXPECT_CHANGED_KEYS",
                "ADE_DATA_DIFF_EXPECT_MISSING_KEYS",
                "ADE_DATA_DIFF_EXPECT_EXTRA_KEYS",
            ],
        }, indent=2))
        return 1

    try:
        source = connector_from_args({"platform": source_platform})
        target = connector_from_args({"platform": target_platform})
    except ExternalConnectionUnavailable as exc:
        return _skip(redact_string(str(exc)))

    environment = {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "source_platform": source.platform,
        "target_platform": target.platform,
        "source_table": source_table,
        "target_table": target_table,
        "key_columns": list(keys),
        "compare_columns": list(compare or ()),
        "partition_strategy": os.getenv("ADE_DATA_DIFF_PARTITION_STRATEGY", "AUTO"),
        "max_partition_rows": max_partition_rows,
        "detail_limit": detail_limit,
        "timeout_seconds": timeout_seconds,
        "minimum_rows": MIN_ROWS,
    }

    try:
        source_count = _count(source, source_table)
        target_count = _count(target, target_table)
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL",
            "stage": "row_count_preflight",
            "reason": f"{type(exc).__name__}: {redact_string(str(exc))}",
            "environment": environment,
        }, indent=2))
        return 1

    if min(source_count, target_count) < MIN_ROWS:
        print(json.dumps({
            "status": "FAIL",
            "stage": "scale_preflight",
            "reason": "external target does not meet the 100M+ certification threshold",
            "source_rows": source_count,
            "target_rows": target_count,
            "minimum_rows": MIN_ROWS,
            "environment": environment,
        }, indent=2))
        return 1

    before_rss = _rss_mb()
    started = time.perf_counter()
    try:
        with _deadline(timeout_seconds):
            result = WarehouseDiffEngine(source, target).hash(
                source_table,
                target_table,
                key_columns=keys,
                compare_columns=compare,
                partition_strategy=environment["partition_strategy"],
                max_partition_rows=max_partition_rows,
                detail_limit=detail_limit,
            )
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL",
            "stage": "data_diff_execution",
            "reason": f"{type(exc).__name__}: {redact_string(str(exc))}",
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_process_rss_mb": round(_rss_mb(), 3),
            "environment": environment,
        }, indent=2))
        return 1

    runtime = time.perf_counter() - started
    after_rss = _rss_mb()
    accuracy, validation = _validate_result(result, expected)
    report = {
        "status": "PASS" if accuracy else "FAIL",
        "certification": "LIVE_VERIFIED_100M_PLUS" if accuracy else "LIVE_100M_PLUS_VALIDATION_FAILED",
        "source_rows": source_count,
        "target_rows": target_count,
        "runtime_seconds": round(runtime, 6),
        "partitions": result.get("partitions"),
        "queries": result.get("query_count"),
        "rows_transferred": result.get("rows_transferred"),
        "raw_rows_transferred": result.get("raw_rows_retrieved", 0),
        "peak_process_rss_mb": round(after_rss, 3),
        "rss_delta_mb": round(max(0.0, after_rss - before_rss), 3),
        "mode": result.get("algorithm"),
        "partition_strategy": result.get("partition_strategy"),
        "diff_status": result.get("status"),
        "validation": validation,
        "environment": environment,
    }
    print(json.dumps(report, indent=2, default=str, sort_keys=True))
    return 0 if accuracy else 1


if __name__ == "__main__":
    raise SystemExit(main())
