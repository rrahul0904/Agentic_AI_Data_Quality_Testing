#!/usr/bin/env python3
"""Analyze Snowflake benchmark evidence into workload fingerprints and acceleration recommendations."""
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


def build_analysis(manifest: dict[str, Any], reports: list[dict[str, Any]]) -> dict[str, Any]:
    query_map = {item["id"]: item for item in manifest["queries"]}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    concurrency_seen: set[int] = set()
    for report in reports:
        concurrency_seen.add(int(report.get("concurrency", 0)))
        for result in report.get("results", []):
            grouped[(result["query_name"], result["variant"])].append(result)

    fingerprints = []
    recommendations = []
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
        }
        fingerprints.append(fingerprint)

        reasons = []
        candidate = None
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
                candidate = "semantic_view_materialization"
            else:
                candidate = "underlying_mart_aggregate_or_dynamic_table"
            if queue_ms > 0:
                candidate += "+warehouse_concurrency"
            if remote_spill > max_spill:
                candidate += "+warehouse_size_or_query_shape"

        if candidate:
            recommendations.append(
                {
                    "query_name": query_name,
                    "variant": variant,
                    "fingerprint": fingerprint["fingerprint"],
                    "candidate": candidate,
                    "reasons": reasons,
                    "confidence": "high" if len(reasons) >= 2 else "medium",
                    "requires_benchmark_validation": True,
                }
            )

    return {
        "status": "ANALYZED",
        "reports": len(reports),
        "concurrency_observed": sorted(value for value in concurrency_seen if value > 0),
        "fingerprints": fingerprints,
        "recommendations": recommendations,
        "policy": (
            "Recommendations are experiments, not automatic physical mutations. "
            "Semantic definitions remain unchanged while physical acceleration is evaluated."
        ),
    }


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.report]
    analysis = build_analysis(manifest, reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "recommendations": len(analysis["recommendations"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
