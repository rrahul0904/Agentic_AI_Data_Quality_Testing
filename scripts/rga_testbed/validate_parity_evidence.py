#!/usr/bin/env python3
"""Validate cross-consumer parity evidence against the generated parity manifest."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

CONSUMERS = ("snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return float(stripped)
        except ValueError:
            return stripped
    return value


def _normalize_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        upper = {str(key).upper(): value for key, value in row.items()}
        normalized.append({column: _normalize_scalar(upper.get(column.upper())) for column in columns})
    return sorted(normalized, key=lambda row: tuple(str(row.get(column)) for column in columns))


def _equal(left: Any, right: Any, tolerance: float) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        if math.isnan(left) and math.isnan(right):
            return True
        return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)
    return left == right


def compare_rows(reference: list[dict[str, Any]], candidate: list[dict[str, Any]], columns: list[str], tolerance: float) -> list[str]:
    errors: list[str] = []
    if len(reference) != len(candidate):
        errors.append(f"row_count mismatch: expected {len(reference)}, got {len(candidate)}")
        return errors
    for index, (expected_row, actual_row) in enumerate(zip(reference, candidate), start=1):
        for column in columns:
            if not _equal(expected_row.get(column), actual_row.get(column), tolerance):
                errors.append(
                    f"row {index} column {column} mismatch: expected {expected_row.get(column)!r}, got {actual_row.get(column)!r}"
                )
    return errors


def validate_case(case: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    case_id = case["id"]
    columns = case["dimensions"] + case["metrics"]
    tolerance = float(case["acceptance"].get("numeric_tolerance", 1e-9))
    evidence: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for consumer in CONSUMERS:
        path = evidence_dir / f"{case_id}.{consumer}.json"
        if not path.exists():
            errors.append(f"missing evidence: {path.name}")
            continue
        payload = load_json(path)
        if payload.get("case_id") != case_id:
            errors.append(f"{consumer}: case_id mismatch")
        if payload.get("consumer") != consumer:
            errors.append(f"{consumer}: consumer mismatch")
        if not payload.get("security_context"):
            errors.append(f"{consumer}: security_context is required")
        if not isinstance(payload.get("rows"), list):
            errors.append(f"{consumer}: rows must be a list")
            continue
        evidence[consumer] = payload

    reference_payload = evidence.get("snowflake_semantic_view")
    if reference_payload:
        reference_security = reference_payload.get("security_context")
        reference_rows = _normalize_rows(reference_payload["rows"], columns)
        for consumer in CONSUMERS[1:]:
            payload = evidence.get(consumer)
            if not payload:
                continue
            if case["acceptance"].get("same_security_context", True) and payload.get("security_context") != reference_security:
                errors.append(
                    f"{consumer}: security_context mismatch: expected {reference_security!r}, got {payload.get('security_context')!r}"
                )
            candidate_rows = _normalize_rows(payload["rows"], columns)
            for error in compare_rows(reference_rows, candidate_rows, columns, tolerance):
                errors.append(f"{consumer}: {error}")

    return {
        "case_id": case_id,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "evidence_consumers": sorted(evidence),
    }


def validate(manifest_path: Path, evidence_dir: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    results = [validate_case(case, evidence_dir) for case in manifest["cases"]]
    failed = sum(item["status"] == "FAIL" for item in results)
    return {
        "status": "PASS" if failed == 0 else "FAIL",
        "case_count": len(results),
        "failed_cases": failed,
        "results": results,
    }


def main() -> int:
    args = parse_args()
    report = validate(args.manifest, args.evidence_dir)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
