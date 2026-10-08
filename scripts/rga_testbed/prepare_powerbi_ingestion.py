#!/usr/bin/env python3
"""Prepare Power BI PBIX/PBIT semantic models for Snowflake Semantic View Autopilot ingestion."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MAX_BYTES = 250 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pbix", ".pbit"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assess(path: Path) -> dict:
    errors: list[str] = []
    warnings = [
        "Report-level measures are not fully supported by Snowflake Power BI ingestion.",
        "Time-intelligence functions such as PREVIOUSMONTH, SAMEPERIODLASTYEAR, and TOTALYTD require manual review.",
        "Parameterized Snowflake connections must have non-null database/schema parameter values before export.",
        "Ingestion processes the full Power BI semantic model rather than a dashboard-scoped subset.",
    ]
    if not path.exists() or not path.is_file():
        errors.append(f"Power BI file not found: {path}")
        size = 0
        file_hash = None
    else:
        size = path.stat().st_size
        file_hash = sha256(path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            errors.append("Snowflake Power BI ingestion accepts .pbix or .pbit files")
        if size > MAX_BYTES:
            errors.append(f"Power BI file exceeds Snowflake's 250 MB ingestion limit: {size} bytes")

    return {
        "status": "READY_FOR_AUTOPILOT" if not errors else "NOT_READY",
        "file": str(path),
        "extension": path.suffix.lower(),
        "bytes": size,
        "sha256": file_hash,
        "errors": errors,
        "warnings": warnings,
        "snowflake_handoff": {
            "surface": "Semantic View Autopilot",
            "required_stage_write_access": True,
            "required_underlying_table_read_access": True,
            "expected_preservation": [
                "table_and_column_names",
                "relationships",
                "supported_dax_measures",
                "single_table_calculated_columns",
                "renamed_tables_and_columns",
                "primary_keys",
            ],
            "post_ingestion_required": [
                "review_generated_semantic_view",
                "compare_metrics_with_canonical_contract",
                "run_cross_consumer_parity_suite",
                "promote_snowflake_semantic_view_as_governed_source",
            ],
        },
    }


def main() -> int:
    args = parse_args()
    report = assess(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, indent=2))
    return 0 if report["status"] == "READY_FOR_AUTOPILOT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
