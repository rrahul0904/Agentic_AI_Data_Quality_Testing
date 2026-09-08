#!/usr/bin/env python3
"""Deterministic local large-scale Data Diff benchmark.

The benchmark generates data inside DuckDB with range() and keeps comparison
pushdown inside the warehouse. It never materializes the benchmark data set as
Python rows. The default suite covers 10K, 100K, 1M and 10M rows.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import time
from pathlib import Path
from typing import Any, Iterable

import duckdb

from agentic_data_platform.connectors.duckdb import DuckDBConnector
from agentic_data_platform.quality.warehouse_diff import WarehouseDiffEngine


DEFAULT_SIZES = (10_000, 100_000, 1_000_000, 10_000_000)


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS reports bytes.
    if platform.system() == "Darwin":
        return value / (1024 * 1024)
    return value / 1024


def _prepare(connection: Any, row_count: int, changed_id: int) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS bench")
    connection.execute(
        "CREATE OR REPLACE VIEW bench.source_rows AS "
        f"SELECT i::BIGINT AS id, ((i * 17) % 10000)::BIGINT AS amount FROM range({row_count}) t(i)"
    )
    connection.execute(
        "CREATE OR REPLACE VIEW bench.target_rows AS "
        "SELECT id, CASE WHEN id = "
        f"{changed_id} THEN amount + 1 ELSE amount END::BIGINT AS amount FROM bench.source_rows"
    )


def run_case(row_count: int, *, max_partition_rows: int = 50_000) -> dict[str, Any]:
    if row_count <= 0:
        raise ValueError("row_count must be positive")
    changed_id = row_count // 2
    connection = duckdb.connect(database=":memory:")
    try:
        _prepare(connection, row_count, changed_id)
        connector = DuckDBConnector(connection)
        engine = WarehouseDiffEngine(connector, connector)
        before_rss = _rss_mb()
        started = time.perf_counter()
        result = engine.hash(
            "bench.source_rows",
            "bench.target_rows",
            key_columns=["id"],
            compare_columns=["amount"],
            partition_strategy="NUMERIC_RANGE",
            max_partition_rows=max_partition_rows,
            detail_limit=10,
        )
        runtime = time.perf_counter() - started
        after_rss = _rss_mb()
        expected_key = [changed_id]
        accuracy = (
            result.get("status") == "FAIL"
            and expected_key in result.get("changed_keys", [])
            and not result.get("missing_keys")
            and not result.get("extra_keys")
        )
        return {
            "row_count": row_count,
            "runtime_seconds": round(runtime, 6),
            "partitions": int(result.get("partitions", 0)),
            "eliminated_partitions": int(result.get("eliminated_partitions", 0)),
            "queries": int(result.get("query_count", 0)),
            "bytes_scanned": None,
            "bytes_scanned_status": "NOT_AVAILABLE_FROM_DUCKDB_CONNECTOR",
            "rows_transferred": int(result.get("rows_transferred", 0)),
            "raw_rows_transferred": int(result.get("raw_rows_retrieved", 0)),
            "peak_process_rss_mb": round(after_rss, 3),
            "rss_delta_mb": round(max(0.0, after_rss - before_rss), 3),
            "mode": "HASH_DIFF_NUMERIC_RANGE_WAREHOUSE_PUSHDOWN",
            "partition_strategy": result.get("partition_strategy"),
            "result_accuracy": bool(accuracy),
            "expected_changed_key": expected_key,
            "changed_keys": result.get("changed_keys", []),
            "warehouse_pushdown": bool(result.get("warehouse_pushdown")),
        }
    finally:
        connection.close()


def run_suite(sizes: Iterable[int]) -> dict[str, Any]:
    cases = [run_case(int(size)) for size in sizes]
    return {
        "benchmark": "local_data_diff_scale",
        "engine": "DuckDB",
        "dataset_generation": "warehouse-native range() views",
        "full_default_sizes": list(DEFAULT_SIZES),
        "cases": cases,
        "status": "PASS" if cases and all(item["result_accuracy"] for item in cases) else "FAIL",
        "claims": {
            "100m_plus": "NOT_RUN_LOCAL; use scripts/live_data_diff_100m.py with an actual external target",
        },
    }


def _parse_sizes(value: str) -> tuple[int, ...]:
    result = tuple(int(item.replace("_", "").strip()) for item in value.split(",") if item.strip())
    if not result:
        raise argparse.ArgumentTypeError("at least one benchmark size is required")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=_parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--output", default="artifacts/data-diff-benchmark.json")
    args = parser.parse_args()
    report = run_suite(args.sizes)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
