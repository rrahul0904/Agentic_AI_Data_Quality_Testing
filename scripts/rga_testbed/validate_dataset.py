#!/usr/bin/env python3
"""Validate manifest checksums, row counts, and key business invariants for RGA synthetic data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/rga_testbed"))
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_entity(root: Path, entity: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted((root / "csv" / entity).glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def validate(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    observed_counts: dict[str, int] = {}
    for item in manifest["files"]:
        path = root / item["file"]
        if not path.exists():
            errors.append(f"missing file: {item['file']}")
            continue
        if sha256(path) != item["checksum"]:
            errors.append(f"checksum mismatch: {item['file']}")
        with path.open(newline="", encoding="utf-8") as handle:
            count = sum(1 for _ in csv.DictReader(handle))
        if count != item["row_count"]:
            errors.append(f"row count mismatch: {item['file']} expected={item['row_count']} actual={count}")
        observed_counts[item["entity"]] = observed_counts.get(item["entity"], 0) + count

    policies = read_entity(root, "policies")
    policy_ids = {row["policy_id"] for row in policies}
    treaty_ids = {row["treaty_id"] for row in read_entity(root, "treaties")}
    insured_ids = {row["insured_id"] for row in read_entity(root, "insured_lives")}
    for row in policies:
        if row["treaty_id"] not in treaty_ids:
            errors.append(f"policy {row['policy_id']} references missing treaty")
        if row["insured_id"] not in insured_ids:
            errors.append(f"policy {row['policy_id']} references missing insured")
        if float(row["sum_assured"]) <= 0 or float(row["annual_premium"]) <= 0:
            errors.append(f"policy {row['policy_id']} has non-positive economics")

    claims = read_entity(root, "claims")
    for row in claims:
        if row["policy_id"] not in policy_ids:
            errors.append(f"claim {row['claim_id']} references missing policy")
        if row["reported_date"] < row["event_date"]:
            errors.append(f"claim {row['claim_id']} reported before event")
        if float(row["ceded_claim_amount"]) > float(row["claim_amount"]):
            errors.append(f"claim {row['claim_id']} ceded amount exceeds gross claim")

    expected = manifest.get("counts", {})
    for entity, count in expected.items():
        if observed_counts.get(entity, 0) != count:
            errors.append(f"manifest count mismatch for {entity}: expected={count} actual={observed_counts.get(entity, 0)}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "counts": observed_counts}


def main() -> int:
    result = validate(parse_args().input)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
