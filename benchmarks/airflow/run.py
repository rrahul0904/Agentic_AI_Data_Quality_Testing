#!/usr/bin/env python3
"""Bounded Airflow static-analysis benchmark with correctness/runtime evidence."""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path

from agentic_data_platform.airflow_compat import AirflowControlPlane

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "hospitality-snowflake-data-platform"


def main() -> int:
    tracemalloc.start()
    started = time.perf_counter()
    control = AirflowControlPlane(PROJECT)
    inventory = control.inventory()
    quality = control.quality_scan()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {
        "project": str(PROJECT),
        "dag_count": inventory["dag_count"],
        "parse_errors": len(inventory["parse_errors"]),
        "finding_count": quality["finding_count"],
        "runtime_seconds": round(elapsed, 6),
        "peak_memory_bytes": peak,
        "correctness_gate": inventory["dag_count"] >= 40 and not inventory["parse_errors"],
    }
    print(json.dumps(result, indent=2))
    return 0 if result["correctness_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
