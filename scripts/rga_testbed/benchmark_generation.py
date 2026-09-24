#!/usr/bin/env python3
"""Benchmark bounded-memory RGA synthetic data generation."""
from __future__ import annotations

import argparse
import json
import platform
import resource
import time
from datetime import date
from pathlib import Path
from typing import Any

try:
    from scripts.rga_testbed.generate_data import build_dataset, load_config
except ModuleNotFoundError:
    from generate_data import build_dataset, load_config

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rga_domain.yml"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_scale_benchmark"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        default="tiny",
        choices=("tiny", "small", "medium", "large", "stress"),
    )
    parser.add_argument("--policies", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reference-date", default="2026-09-01")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def peak_rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return raw / (1024.0 * 1024.0)
    return raw / 1024.0


def benchmark(
    *,
    config_path: Path,
    preset: str,
    policies: int,
    seed: int,
    reference_date: date,
    output: Path,
) -> dict[str, Any]:
    if policies < 1:
        raise ValueError("policies must be positive")
    config = load_config(config_path)
    started = time.perf_counter()
    manifest = build_dataset(
        config=config,
        preset_name=preset,
        seed=seed,
        reference_date=reference_date,
        output=output,
        policy_override=policies,
    )
    elapsed = time.perf_counter() - started
    total_rows = sum(int(value) for value in manifest["counts"].values())
    total_bytes = sum(int(item["byte_count"]) for item in manifest["files"])
    file_count = len(manifest["files"])
    rows_per_second = total_rows / elapsed if elapsed else None
    policies_per_second = policies / elapsed if elapsed else None

    return {
        "status": "PASS",
        "benchmark_version": 1,
        "preset": preset,
        "policies": policies,
        "seed": seed,
        "reference_date": reference_date.isoformat(),
        "generation_id": manifest["generation_id"],
        "row_emission": "streaming_rotating_csv",
        "configured_rows_per_file": manifest["settings"]["rows_per_file"],
        "total_rows": total_rows,
        "entity_counts": manifest["counts"],
        "file_count": file_count,
        "total_bytes": total_bytes,
        "elapsed_seconds": round(elapsed, 6),
        "policies_per_second": (
            round(policies_per_second, 2)
            if policies_per_second is not None
            else None
        ),
        "rows_per_second": (
            round(rows_per_second, 2)
            if rows_per_second is not None
            else None
        ),
        "peak_rss_mb": round(peak_rss_mb(), 2),
        "output": str(output),
        "scope": (
            "Local generator throughput and process peak RSS only. "
            "This is not proof of Snowflake load/query scale or 100M-policy capacity."
        ),
    }


def main() -> int:
    args = parse_args()
    try:
        report = benchmark(
            config_path=args.config,
            preset=args.preset,
            policies=args.policies,
            seed=args.seed,
            reference_date=date.fromisoformat(args.reference_date),
            output=args.output,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
