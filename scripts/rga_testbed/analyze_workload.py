#!/usr/bin/env python3
"""Analyze Snowflake workload evidence into guarded physical-acceleration experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "rga-snowflake-data-platform" / "benchmarks" / "manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_workload_analysis.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def percentile(values: Iterable[float], pct: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _shape(query: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": sorted(query.get("metrics", [])),
        "dimensions": sorted(query.get("dimensions", [])),
    }


def _fingerprint(shape: dict[str, Any]) -> str:
    payload = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _safe_ident(value: str) -> str:
    return str(value).replace('"', '""')


def _scan_ratio(rows: list[dict[str, Any]]) -> float | None:
    scanned = sum(int(item.get("partitions_scanned") or 0) for item in rows)
    total = sum(int(item.get("partitions_total") or 0) for item in rows)
    if total <= 0:
        return None
    return scanned / total


def _mean(values: Iterable[float]) -> float | None:
    data = [float(value) for value in values]
    return sum(data) / len(data) if data else None


def _recommendation(
    *,
    query_name: str,
    variant: str,
    fingerprint: str,
    candidates: list[str],
    reasons: list[str],
    confidence: str,
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    # candidate is retained for compatibility with the earlier operator/report schema.
    return {
        "query_name": query_name,
        "variant": variant,
        "fingerprint": fingerprint,
        "candidate": "+".join(candidates),
        "candidates": candidates,
        "reasons": reasons,
        "confidence": confidence,
        "experiments": experiments,
        "requires_benchmark_validation": True,
        "automatic_mutation_allowed": False,
    }


def _benchmark_analysis(
    manifest: dict[str, Any],
    reports: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[int]]:
    query_map = {item["id"]: item for item in manifest["queries"]}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    concurrency_seen: set[int] = set()
    for report in reports:
        concurrency_seen.add(int(report.get("concurrency", 0)))
        for result in report.get("results", []):
            grouped[(result["query_name"], result["variant"])].append(result)

    fingerprints: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    target_p95 = float(manifest.get("acceptance", {}).get("target_p95_ms", 5000))
    max_spill = int(manifest.get("acceptance", {}).get("max_remote_spill_bytes", 0))

    for (query_name, variant), rows in sorted(grouped.items()):
        query = query_map[query_name]
        shape = _shape(query)
        passed = [item for item in rows if item.get("status") == "PASS"]
        elapsed = [float(item.get("client_elapsed_ms") or 0) for item in passed]
        bytes_scanned = sum(int(item.get("bytes_scanned") or 0) for item in passed)
        queue_ms = sum(int(item.get("queued_overload_time") or 0) for item in passed)
        remote_spill = sum(int(item.get("bytes_spilled_to_remote_storage") or 0) for item in passed)
        qas_bytes = sum(int(item.get("query_acceleration_bytes_scanned") or 0) for item in passed)
        qas_upper = max(
            [float(item.get("query_acceleration_upper_limit_scale_factor") or 0) for item in passed]
            or [0.0]
        )
        scan_ratio = _scan_ratio(passed)
        cache_pct = _mean(
            item.get("percentage_scanned_from_cache")
            for item in passed
            if item.get("percentage_scanned_from_cache") is not None
        )
        query_load = _mean(
            item.get("query_load_percent")
            for item in passed
            if item.get("query_load_percent") is not None
        )
        p95 = percentile(elapsed, 0.95)
        fingerprint = {
            "query_name": query_name,
            "variant": variant,
            "fingerprint": _fingerprint(shape),
            "shape": shape,
            "executions": len(rows),
            "passed": len(passed),
            "p95_client_elapsed_ms": round(p95, 3) if p95 is not None else None,
            "bytes_scanned": bytes_scanned,
            "queued_overload_ms": queue_ms,
            "remote_spill_bytes": remote_spill,
            "partition_scan_ratio": round(scan_ratio, 4) if scan_ratio is not None else None,
            "average_cache_pct": round(cache_pct, 3) if cache_pct is not None else None,
            "average_query_load_pct": round(query_load, 3) if query_load is not None else None,
            "query_acceleration_bytes_scanned": qas_bytes,
            "query_acceleration_upper_limit_scale_factor": qas_upper,
            "query_hashes": sorted(
                {str(item["query_hash"]) for item in passed if item.get("query_hash")}
            ),
            "query_parameterized_hashes": sorted(
                {
                    str(item["query_parameterized_hash"])
                    for item in passed
                    if item.get("query_parameterized_hash")
                }
            ),
        }
        fingerprints.append(fingerprint)

        reasons: list[str] = []
        candidates: list[str] = []
        experiments: list[dict[str, Any]] = []
        if p95 is not None and p95 > target_p95:
            reasons.append(f"p95 {p95:.1f}ms exceeds target {target_p95:.1f}ms")
        if remote_spill > max_spill:
            reasons.append(f"remote spill {remote_spill} exceeds target {max_spill}")
        if queue_ms > 0:
            reasons.append(f"warehouse overload queue time observed: {queue_ms}ms")
        if bytes_scanned > 0 and len(passed) >= 2:
            reasons.append("repeated scan-heavy shape")

        if reasons:
            if variant == "semantic":
                candidates.append("semantic_view_materialization")
                experiments.append(
                    {
                        "type": "semantic_view_materialization",
                        "action": "benchmark existing generated materialization candidate",
                        "mutation": "separate guarded semantic-materialization sync",
                    }
                )
            else:
                candidates.append("underlying_mart_aggregate_or_dynamic_table")
                experiments.append(
                    {
                        "type": "aggregate_or_dynamic_table",
                        "action": "benchmark a physically aggregated copy at the verified query grain",
                        "mutation": "template-only until before/after benchmark passes",
                    }
                )

        if queue_ms > 0:
            candidates.append("warehouse_concurrency")
            experiments.append(
                {
                    "type": "warehouse_concurrency",
                    "action": "compare multi-cluster/concurrency configuration under identical sweep",
                    "evidence": {"queued_overload_ms": queue_ms},
                }
            )
        if remote_spill > max_spill:
            candidates.append("warehouse_size_or_query_shape")
            experiments.append(
                {
                    "type": "warehouse_size_or_query_shape",
                    "action": "compare one warehouse size step and/or reduce intermediate data shape",
                    "evidence": {"remote_spill_bytes": remote_spill},
                }
            )
        if qas_upper > 0:
            candidates.append("query_acceleration_service")
            representative = next(
                (str(item["query_id"]) for item in passed if item.get("query_id")),
                None,
            )
            experiments.append(
                {
                    "type": "query_acceleration_service",
                    "action": "estimate QAS benefit before changing warehouse configuration",
                    "representative_query_id": representative,
                    "estimate_sql": (
                        f"SELECT SYSTEM$ESTIMATE_QUERY_ACCELERATION('{representative}');"
                        if representative
                        else None
                    ),
                    "already_accelerated_bytes": qas_bytes,
                    "upper_limit_scale_factor": qas_upper,
                }
            )

        if candidates:
            recommendations.append(
                _recommendation(
                    query_name=query_name,
                    variant=variant,
                    fingerprint=fingerprint["fingerprint"],
                    candidates=candidates,
                    reasons=reasons or ["Snowflake QAS eligibility signal observed"],
                    confidence="high" if len(reasons) >= 2 else "medium",
                    experiments=experiments,
                )
            )

    return fingerprints, recommendations, concurrency_seen


def _history_analysis(history: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not history:
        return [], []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in history.get("queries", []):
        key = str(
            item.get("query_parameterized_hash")
            or item.get("query_hash")
            or item.get("sql_sha256")
            or item.get("query_id")
        )
        grouped[key].append(item)

    fingerprints: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        elapsed = [float(item.get("total_elapsed_time") or 0) for item in rows]
        queue_ms = sum(int(item.get("queued_overload_time") or 0) for item in rows)
        spill = sum(int(item.get("bytes_spilled_to_remote_storage") or 0) for item in rows)
        bytes_scanned = sum(int(item.get("bytes_scanned") or 0) for item in rows)
        qas_upper = max(
            [float(item.get("query_acceleration_upper_limit_scale_factor") or 0) for item in rows]
            or [0.0]
        )
        qas_bytes = sum(int(item.get("query_acceleration_bytes_scanned") or 0) for item in rows)
        scan_ratio = _scan_ratio(rows)
        tables = sorted(
            {
                str(table).upper()
                for item in rows
                for table in (item.get("shape", {}).get("tables", []) or [])
            }
        )
        predicate_pairs = sorted(
            {
                (
                    str(predicate.get("column", "")).upper(),
                    str(predicate.get("operator", "")).upper(),
                )
                for item in rows
                for predicate in (item.get("shape", {}).get("predicates", []) or [])
                if predicate.get("column")
            }
        )
        representative_query_id = next(
            (str(item["query_id"]) for item in rows if item.get("query_id")),
            None,
        )
        fingerprint = {
            "query_parameterized_hash": key,
            "executions": len(rows),
            "p95_total_elapsed_ms": round(percentile(elapsed, 0.95) or 0, 3),
            "bytes_scanned": bytes_scanned,
            "queued_overload_ms": queue_ms,
            "remote_spill_bytes": spill,
            "partition_scan_ratio": round(scan_ratio, 4) if scan_ratio is not None else None,
            "query_acceleration_bytes_scanned": qas_bytes,
            "query_acceleration_upper_limit_scale_factor": qas_upper,
            "tables": tables,
            "predicates": [
                {"column": column, "operator": operator}
                for column, operator in predicate_pairs
            ],
            "representative_query_id": representative_query_id,
        }
        fingerprints.append(fingerprint)

        if qas_upper > 0 and representative_query_id:
            experiments.append(
                {
                    "fingerprint": key,
                    "type": "query_acceleration_service",
                    "confidence": "high",
                    "reason": "Snowflake reported a positive QAS upper-limit scale factor",
                    "representative_query_id": representative_query_id,
                    "estimate_sql": (
                        f"SELECT SYSTEM$ESTIMATE_QUERY_ACCELERATION('{representative_query_id}');"
                    ),
                    "automatic_mutation_allowed": False,
                }
            )

        if queue_ms > 0:
            experiments.append(
                {
                    "fingerprint": key,
                    "type": "warehouse_concurrency",
                    "confidence": "high",
                    "reason": f"{queue_ms}ms queued overload observed",
                    "automatic_mutation_allowed": False,
                }
            )

        equality_columns = sorted(
            {
                column
                for column, operator in predicate_pairs
                if operator in {"=", "IN"}
            }
        )
        filter_columns = sorted({column for column, _ in predicate_pairs})
        repeated = len(rows) >= 3
        poor_pruning = scan_ratio is not None and scan_ratio >= 0.80

        # Clustering needs repeated selective/filter workload plus poor partition pruning.
        if repeated and poor_pruning and filter_columns and tables:
            for table in tables[:3]:
                columns = filter_columns[:4]
                expr = ", ".join(columns)
                experiments.append(
                    {
                        "fingerprint": key,
                        "type": "clustering_diagnostic",
                        "confidence": "medium",
                        "reason": (
                            f"repeated filtered shape scans {scan_ratio:.0%} of observed partitions"
                        ),
                        "table": table,
                        "columns": columns,
                        "diagnostic_sql": (
                            "SELECT SYSTEM$CLUSTERING_INFORMATION("
                            f"'{_safe_ident(table)}', '({expr})');"
                        ),
                        "mutation_sql": (
                            f"ALTER TABLE {table} CLUSTER BY ({expr});"
                        ),
                        "mutation_guard": (
                            "Do not execute until clustering diagnostics and before/after cost/performance "
                            "evidence justify maintenance cost."
                        ),
                        "automatic_mutation_allowed": False,
                    }
                )

        # Search Optimization is narrower: repeated equality/IN lookup shape on a known table.
        if repeated and poor_pruning and equality_columns and tables:
            for table in tables[:3]:
                columns = equality_columns[:4]
                target = ", ".join(columns)
                experiments.append(
                    {
                        "fingerprint": key,
                        "type": "search_optimization_cost_estimate",
                        "confidence": "medium",
                        "reason": (
                            "repeated equality/IN predicates with poor observed partition pruning"
                        ),
                        "table": table,
                        "columns": columns,
                        "estimate_sql": (
                            "SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS("
                            f"'{_safe_ident(table)}', 'EQUALITY({target})');"
                        ),
                        "mutation_sql": (
                            f"ALTER TABLE {table} ADD SEARCH OPTIMIZATION ON EQUALITY({target});"
                        ),
                        "mutation_guard": (
                            "Estimate cost first; enable only after selective lookup benefit and "
                            "maintenance/storage cost are accepted."
                        ),
                        "automatic_mutation_allowed": False,
                    }
                )

    return fingerprints, experiments


def build_analysis(
    manifest: dict[str, Any],
    reports: list[dict[str, Any]],
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    benchmark_fingerprints, recommendations, concurrency_seen = _benchmark_analysis(
        manifest,
        reports,
    )
    history_fingerprints, history_experiments = _history_analysis(history)

    return {
        "status": "ANALYZED",
        "reports": len(reports),
        "concurrency_observed": sorted(value for value in concurrency_seen if value > 0),
        "fingerprints": benchmark_fingerprints,
        "recommendations": recommendations,
        "query_history": {
            "present": history is not None,
            "query_count": int(history.get("query_count", 0)) if history else 0,
            "fingerprints": history_fingerprints,
            "experiments": history_experiments,
        },
        "policy": (
            "Recommendations are experiments, not automatic physical mutations. "
            "Semantic definitions remain unchanged while physical acceleration is evaluated. "
            "Clustering/Search Optimization require predicate and pruning evidence; "
            "QAS requires Snowflake eligibility evidence; warehouse concurrency requires queue evidence."
        ),
        "current_snowflake_context": {
            "new_clustering_behavior": (
                "Newly clustered tables use Snowflake Optima Clustering as of 2026-09-01; "
                "the engine proposes diagnostics first and never manual reclustering."
            ),
            "search_optimization": (
                "Cost estimation precedes enablement; equality/IN recommendations require repeated "
                "lookup predicates and poor pruning."
            ),
        },
    }


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.report]
    history = json.loads(args.history.read_text(encoding="utf-8")) if args.history else None
    analysis = build_analysis(manifest, reports, history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(args.output),
                "recommendations": len(analysis["recommendations"]),
                "history_experiments": len(analysis["query_history"]["experiments"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
