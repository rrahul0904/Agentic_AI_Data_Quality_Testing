#!/usr/bin/env python3
"""Ingest captured Power BI or Excel rows into governed parity evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ALLOWED_CONSUMERS = ("power_bi", "excel")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--consumer", choices=ALLOWED_CONSUMERS, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--security-context", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            return [dict(row) for row in reader]
    if suffix == ".json":
        payload = load_json(path)
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            rows = payload["rows"]
        else:
            raise ValueError("JSON must be a row list or an object containing rows")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("Every JSON row must be an object")
        return [dict(row) for row in rows]
    raise ValueError("Input must be .csv or .json")


def expected_case(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in manifest.get("cases", []):
        if str(case.get("id")) == case_id:
            return case
    raise ValueError(f"Unknown parity case: {case_id}")


def normalize_rows(rows: list[dict[str, Any]], expected_columns: list[str]) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("Captured evidence rows must not be empty")
    expected = [str(column).upper() for column in expected_columns]
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        upper = {str(key).upper(): value for key, value in row.items()}
        actual = sorted(upper)
        if actual != sorted(expected):
            raise ValueError(
                f"row {index} column mismatch: expected {expected}, got {actual}"
            )
        normalized.append({column: upper[column] for column in expected})
    return normalized


def ingest(
    manifest_path: Path,
    evidence_dir: Path,
    *,
    case_id: str,
    consumer: str,
    input_path: Path,
    security_context: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    if consumer not in ALLOWED_CONSUMERS:
        raise ValueError(
            "External file ingestion is restricted to Power BI and Excel; "
            "Snowflake/Agent evidence must use governed live capture."
        )
    if not security_context.strip():
        raise ValueError("security_context is required")
    if not input_path.exists():
        raise FileNotFoundError(f"Evidence input not found: {input_path}")

    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("Parity manifest must be a JSON object")
    case = expected_case(manifest, case_id)
    expected_columns = case.get("dimensions", []) + case.get("metrics", [])
    rows = normalize_rows(load_rows(input_path), expected_columns)

    evidence_dir.mkdir(parents=True, exist_ok=True)
    output = evidence_dir / f"{case_id}.{consumer}.json"
    if output.exists() and not overwrite:
        existing = load_json(output)
        if isinstance(existing, dict) and existing.get("capture_status") == "CAPTURED":
            raise ValueError(
                f"Captured evidence already exists: {output}. Use --overwrite to replace it."
            )

    payload = {
        "case_id": case_id,
        "business_question": case.get("business_question"),
        "consumer": consumer,
        "security_context": security_context,
        "capture_status": "CAPTURED",
        "capture_method": "external_file_import",
        "source_file": str(input_path),
        "source_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "expected_dimensions": case.get("dimensions", []),
        "expected_metrics": case.get("metrics", []),
        "rows": rows,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PASS",
        "case_id": case_id,
        "consumer": consumer,
        "security_context": security_context,
        "row_count": len(rows),
        "output": str(output),
    }


def main() -> int:
    args = parse_args()
    try:
        report = ingest(
            args.manifest,
            args.evidence_dir,
            case_id=args.case_id,
            consumer=args.consumer,
            input_path=args.input,
            security_context=args.security_context,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
