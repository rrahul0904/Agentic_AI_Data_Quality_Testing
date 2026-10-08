#!/usr/bin/env python3
"""Evaluate before/after Snowflake benchmark evidence for a physical optimization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, action="append", required=True)
    parser.add_argument("--after", type=Path, action="append", required=True)
    parser.add_argument(
        "--target-variant",
        choices=("direct", "semantic", "both"),
        default="both",
    )
    parser.add_argument("--min-p95-improvement-pct", type=float, default=10.0)
    parser.add_argument("--max-scan-regression-pct", type=float, default=25.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _load(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def _by_concurrency(reports: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for report in reports:
        concurrency = int(report.get("concurrency", 0))
        if concurrency <= 0:
            raise ValueError("every benchmark report must contain positive concurrency")
        if concurrency in result:
            raise ValueError(f"duplicate benchmark report for concurrency={concurrency}")
        result[concurrency] = report
    return result


def _signatures(report: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    values: dict[tuple[str, str], set[str]] = {}
    for item in report.get("results", []):
        if item.get("status") != "PASS":
            continue
        query_name = str(item.get("query_name") or "")
        variant = str(item.get("variant") or "")
        signature = item.get("result_sha256")
        if query_name and variant and signature:
            values.setdefault((query_name, variant), set()).add(str(signature))
    return values


def _pct_change(before: float, after: float) -> float | None:
    if before == 0:
        return 0.0 if after == 0 else None
    return ((after - before) / before) * 100.0


def evaluate(
    before_reports: list[dict[str, Any]],
    after_reports: list[dict[str, Any]],
    *,
    target_variant: str = "both",
    min_p95_improvement_pct: float = 10.0,
    max_scan_regression_pct: float = 25.0,
) -> dict[str, Any]:
    if min_p95_improvement_pct < 0:
        raise ValueError("min_p95_improvement_pct must be non-negative")
    if max_scan_regression_pct < 0:
        raise ValueError("max_scan_regression_pct must be non-negative")

    before = _by_concurrency(before_reports)
    after = _by_concurrency(after_reports)
    if set(before) != set(after):
        raise ValueError(
            "before/after concurrency sets must match exactly: "
            f"before={sorted(before)} after={sorted(after)}"
        )

    variants = (
        ("direct", "semantic")
        if target_variant == "both"
        else (target_variant,)
    )
    comparisons: list[dict[str, Any]] = []
    correctness_failures: list[str] = []
    regression_failures: list[str] = []
    insufficient_improvement: list[str] = []

    for concurrency in sorted(before):
        before_report = before[concurrency]
        after_report = after[concurrency]

        if before_report.get("status") != "PASS":
            correctness_failures.append(
                f"before benchmark c{concurrency} did not PASS"
            )
        if after_report.get("status") != "PASS":
            correctness_failures.append(
                f"after benchmark c{concurrency} did not PASS"
            )
        if after_report.get("result_parity", {}).get("status") != "PASS":
            correctness_failures.append(
                f"after direct/semantic parity failed at c{concurrency}"
            )

        before_signatures = _signatures(before_report)
        after_signatures = _signatures(after_report)
        for key, before_values in before_signatures.items():
            if key[1] not in variants:
                continue
            after_values = after_signatures.get(key, set())
            if len(before_values) != 1 or len(after_values) != 1:
                correctness_failures.append(
                    f"unstable/missing result signature for {key[0]} {key[1]} at c{concurrency}"
                )
            elif before_values != after_values:
                correctness_failures.append(
                    f"result signature changed for {key[0]} {key[1]} at c{concurrency}"
                )

        before_variants = before_report.get("summary", {}).get("variants", {})
        after_variants = after_report.get("summary", {}).get("variants", {})
        for variant in variants:
            b = before_variants.get(variant)
            a = after_variants.get(variant)
            if not isinstance(b, dict) or not isinstance(a, dict):
                correctness_failures.append(
                    f"missing {variant} summary at c{concurrency}"
                )
                continue

            b_p95 = b.get("p95_client_elapsed_ms")
            a_p95 = a.get("p95_client_elapsed_ms")
            if b_p95 is None or a_p95 is None:
                correctness_failures.append(
                    f"missing p95 latency for {variant} at c{concurrency}"
                )
                continue
            b_p95 = float(b_p95)
            a_p95 = float(a_p95)
            p95_improvement = (
                ((b_p95 - a_p95) / b_p95) * 100.0
                if b_p95 > 0
                else 0.0
            )

            b_scan = float(b.get("bytes_scanned") or 0)
            a_scan = float(a.get("bytes_scanned") or 0)
            scan_regression = _pct_change(b_scan, a_scan)

            b_queue = int(b.get("queued_overload_ms") or 0)
            a_queue = int(a.get("queued_overload_ms") or 0)
            b_spill = int(b.get("remote_spill_bytes") or 0)
            a_spill = int(a.get("remote_spill_bytes") or 0)

            if a_queue > b_queue:
                regression_failures.append(
                    f"{variant} queue overload regressed at c{concurrency}: {b_queue}->{a_queue}ms"
                )
            if a_spill > b_spill:
                regression_failures.append(
                    f"{variant} remote spill regressed at c{concurrency}: {b_spill}->{a_spill}"
                )
            if (
                scan_regression is not None
                and scan_regression > max_scan_regression_pct
            ):
                regression_failures.append(
                    f"{variant} bytes scanned regressed {scan_regression:.1f}% at c{concurrency}"
                )
            if p95_improvement < min_p95_improvement_pct:
                insufficient_improvement.append(
                    f"{variant} p95 improvement {p95_improvement:.1f}% "
                    f"is below {min_p95_improvement_pct:.1f}% at c{concurrency}"
                )

            comparisons.append(
                {
                    "concurrency": concurrency,
                    "variant": variant,
                    "before_p95_ms": b_p95,
                    "after_p95_ms": a_p95,
                    "p95_improvement_pct": round(p95_improvement, 3),
                    "before_bytes_scanned": int(b_scan),
                    "after_bytes_scanned": int(a_scan),
                    "scan_change_pct": (
                        round(scan_regression, 3)
                        if scan_regression is not None
                        else None
                    ),
                    "before_queue_ms": b_queue,
                    "after_queue_ms": a_queue,
                    "before_remote_spill_bytes": b_spill,
                    "after_remote_spill_bytes": a_spill,
                }
            )

    if correctness_failures or regression_failures:
        decision = "REJECT"
    elif insufficient_improvement:
        decision = "INCONCLUSIVE"
    else:
        decision = "ACCEPT"

    return {
        "status": "PASS",
        "decision": decision,
        "target_variant": target_variant,
        "concurrency": sorted(before),
        "thresholds": {
            "min_p95_improvement_pct": min_p95_improvement_pct,
            "max_scan_regression_pct": max_scan_regression_pct,
        },
        "semantic_contract_preserved": not correctness_failures,
        "performance_regression_free": not regression_failures,
        "performance_threshold_met": not insufficient_improvement,
        "correctness_failures": correctness_failures,
        "regression_failures": regression_failures,
        "insufficient_improvement": insufficient_improvement,
        "comparisons": comparisons,
        "policy": (
            "ACCEPT requires identical result signatures, passing direct/semantic parity, "
            "no queue/spill/scan regression beyond configured thresholds, and the requested "
            "p95 improvement at every tested concurrency/target variant."
        ),
    }


def main() -> int:
    args = parse_args()
    try:
        result = evaluate(
            _load(args.before),
            _load(args.after),
            target_variant=args.target_variant,
            min_p95_improvement_pct=args.min_p95_improvement_pct,
            max_scan_regression_pct=args.max_scan_regression_pct,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
        result["output"] = str(args.output)
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "ACCEPT" else 3


if __name__ == "__main__":
    raise SystemExit(main())
