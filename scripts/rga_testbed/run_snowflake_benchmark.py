#!/usr/bin/env python3
"""Run paired MART vs Semantic View benchmarks against Snowflake.

Live execution is fail-closed: --confirm-live is required. CI uses --dry-run only.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "rga-snowflake-data-platform" / "benchmarks" / "manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_benchmark_results.json"
REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")


@dataclass(frozen=True)
class BenchmarkTask:
    query_name: str
    variant: str
    iteration: int
    sql_file: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mode", choices=("direct", "semantic", "both"), default="both")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not manifest.get("queries"):
        raise ValueError("Benchmark manifest contains no queries")
    return manifest


def validate_request(manifest: Path, concurrency: int, iterations: int, confirm_live: bool, dry_run: bool) -> list[str]:
    errors: list[str] = []
    if not manifest.exists():
        errors.append(f"Benchmark manifest not found: {manifest}")
    if concurrency < 1 or concurrency > 100:
        errors.append("concurrency must be between 1 and 100")
    if iterations < 1 or iterations > 100:
        errors.append("iterations must be between 1 and 100")
    if not dry_run and not confirm_live:
        errors.append("Refusing live Snowflake benchmark without --confirm-live")
    return errors


def build_plan(manifest_path: Path, manifest: dict[str, Any], mode: str, iterations: int) -> list[BenchmarkTask]:
    variants = ("direct", "semantic") if mode == "both" else (mode,)
    tasks: list[BenchmarkTask] = []
    for query in manifest["queries"]:
        for variant in variants:
            file_key = f"{variant}_sql"
            if file_key not in query:
                raise ValueError(f"Query {query.get('id')} is missing {file_key}")
            sql_path = manifest_path.parent / query[file_key]
            if not sql_path.exists():
                raise ValueError(f"Benchmark SQL file not found: {sql_path}")
            for iteration in range(1, iterations + 1):
                tasks.append(BenchmarkTask(query["id"], variant, iteration, sql_path))
    return tasks


def connection_kwargs(env: dict[str, str], query_tag: str) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError("Missing Snowflake environment variables: " + ", ".join(missing))
    kwargs: dict[str, Any] = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "warehouse": env["SNOWFLAKE_WAREHOUSE"],
        "role": env.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        "database": env.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED"),
        "session_parameters": {"QUERY_TAG": query_tag},
    }
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    return kwargs


def _telemetry(cursor: Any, query_id: str) -> dict[str, Any]:
    telemetry_sql = """
select
  query_id,
  total_elapsed_time,
  execution_time,
  compilation_time,
  queued_provisioning_time,
  queued_overload_time,
  bytes_scanned,
  partitions_scanned,
  partitions_total,
  rows_produced,
  percentage_scanned_from_cache,
  bytes_spilled_to_local_storage,
  bytes_spilled_to_remote_storage,
  execution_status,
  error_code,
  error_message
from table(information_schema.query_history(
  end_time_range_start => dateadd('minute', -30, current_timestamp()),
  result_limit => 10000
))
where query_id = %s
"""
    cursor.execute(telemetry_sql, (query_id,))
    row = cursor.fetchone()
    if row is None:
        return {"telemetry_status": "NOT_FOUND"}
    columns = [item[0].lower() for item in cursor.description]
    return {**dict(zip(columns, row)), "telemetry_status": "FOUND"}


def execute_task(task: BenchmarkTask, env: dict[str, str], run_id: str, query_tag_base: str) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live benchmarks") from exc

    sql = task.sql_file.read_text(encoding="utf-8")
    query_tag = f"{query_tag_base}:{run_id}:{task.variant}:{task.query_name}"
    connection = snowflake.connector.connect(**connection_kwargs(env, query_tag))
    started = time.perf_counter()
    query_id: str | None = None
    rows = 0
    try:
        cursor = connection.cursor()
        try:
            query_started = time.perf_counter()
            cursor.execute(sql)
            query_id = cursor.sfqid
            fetched = cursor.fetchall()
            rows = len(fetched)
            wall_elapsed_ms = round((time.perf_counter() - query_started) * 1000, 3)
            metrics = _telemetry(cursor, query_id)
            return {
                "status": "PASS",
                "query_name": task.query_name,
                "variant": task.variant,
                "iteration": task.iteration,
                "query_id": query_id,
                "rows_fetched": rows,
                "client_elapsed_ms": wall_elapsed_ms,
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                **metrics,
            }
        finally:
            cursor.close()
    except Exception as exc:
        return {
            "status": "FAIL",
            "query_name": task.query_name,
            "variant": task.variant,
            "iteration": task.iteration,
            "query_id": query_id,
            "rows_fetched": rows,
            "client_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "error": str(exc),
        }
    finally:
        connection.close()


def percentile(values: Iterable[float], pct: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(results: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] != "PASS" for item in results),
        "wall_seconds": round(wall_seconds, 3),
        "throughput_qps": round(len(results) / wall_seconds, 3) if wall_seconds > 0 else None,
        "variants": {},
    }
    for variant in ("direct", "semantic"):
        subset = [item for item in results if item["variant"] == variant]
        elapsed = [item["client_elapsed_ms"] for item in subset if item["status"] == "PASS"]
        if not subset:
            continue
        summary["variants"][variant] = {
            "total": len(subset),
            "passed": sum(item["status"] == "PASS" for item in subset),
            "failed": sum(item["status"] != "PASS" for item in subset),
            "p50_client_elapsed_ms": round(percentile(elapsed, 0.50), 3) if elapsed else None,
            "p95_client_elapsed_ms": round(percentile(elapsed, 0.95), 3) if elapsed else None,
            "p99_client_elapsed_ms": round(percentile(elapsed, 0.99), 3) if elapsed else None,
            "bytes_scanned": sum(int(item.get("bytes_scanned") or 0) for item in subset if item["status"] == "PASS"),
            "queued_overload_ms": sum(int(item.get("queued_overload_time") or 0) for item in subset if item["status"] == "PASS"),
            "remote_spill_bytes": sum(int(item.get("bytes_spilled_to_remote_storage") or 0) for item in subset if item["status"] == "PASS"),
        }
    return summary


def dry_run_payload(manifest_path: Path, tasks: list[BenchmarkTask], concurrency: int) -> dict[str, Any]:
    return {
        "status": "DRY_RUN",
        "manifest": str(manifest_path),
        "concurrency": concurrency,
        "task_count": len(tasks),
        "queries": sorted({task.query_name for task in tasks}),
        "variants": sorted({task.variant for task in tasks}),
        "sql_files": sorted({str(task.sql_file) for task in tasks}),
    }


def main() -> int:
    args = parse_args()
    errors = validate_request(args.manifest, args.concurrency, args.iterations, args.confirm_live, args.dry_run)
    if errors:
        print(json.dumps({"status": "REFUSED", "errors": errors}, indent=2))
        return 2

    manifest = load_manifest(args.manifest)
    tasks = build_plan(args.manifest, manifest, args.mode, args.iterations)
    if args.dry_run:
        print(json.dumps(dry_run_payload(args.manifest, tasks, args.concurrency), indent=2))
        return 0

    run_id = uuid.uuid4().hex[:12]
    query_tag_base = manifest.get("query_tag", "RGA_SEMANTIC_BENCHMARK")
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(execute_task, task, dict(os.environ), run_id, query_tag_base) for task in tasks]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    wall_seconds = time.perf_counter() - started

    report = {
        "run_id": run_id,
        "query_tag_base": query_tag_base,
        "concurrency": args.concurrency,
        "iterations": args.iterations,
        "mode": args.mode,
        "summary": summarize(results, wall_seconds),
        "results": sorted(results, key=lambda item: (item["query_name"], item["variant"], item["iteration"])),
        "note": "Snowflake QUERY_HISTORY telemetry is reported per query. Warehouse credit attribution is intentionally not estimated per query.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS" if report["summary"]["failed"] == 0 else "FAIL", "output": str(args.output), **report["summary"]}, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
