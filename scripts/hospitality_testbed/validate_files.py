#!/usr/bin/env python3
"""Validate hospitality files against the generation manifest and emit JSON evidence."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from lib import FAIL, PASS, ROOT, evidence_path, load_yaml, sha256_file, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "hospitality")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json-output", type=Path, default=evidence_path("file-validation.json"))
    return parser.parse_args()


def validate(data_dir: Path, manifest_path: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if not manifest_path.is_file():
        return {"status": FAIL, "findings": [{"code": "MANIFEST_MISSING", "path": str(manifest_path)}]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    configured = load_yaml("hospitality_ingestion.yml")["entities"]
    expected_entities = set(configured)
    actual_entities = set(manifest.get("entities", []))
    if actual_entities != expected_entities:
        findings.append({"code": "ENTITY_SET_MISMATCH", "expected": sorted(expected_entities), "actual": sorted(actual_entities)})
    names = [item.get("file") for item in manifest.get("files", [])]
    for name, count in Counter(names).items():
        if count > 1:
            findings.append({"code": "DUPLICATE_FILENAME", "file": name, "count": count})
    verified_rows = 0
    verified_files = 0
    for item in manifest.get("files", []):
        relative = Path(item["file"])
        path = data_dir / relative
        entity = item["entity"]
        if not path.is_file():
            findings.append({"code": "FILE_MISSING", "file": relative.as_posix()})
            continue
        if path.stat().st_size == 0:
            findings.append({"code": "ZERO_BYTE", "file": relative.as_posix()})
        if path.stat().st_size != item["byte_count"]:
            findings.append({"code": "BYTE_COUNT_MISMATCH", "file": relative.as_posix(), "expected": item["byte_count"], "actual": path.stat().st_size})
        checksum = sha256_file(path)
        if checksum != item["checksum"]:
            findings.append({"code": "CHECKSUM_MISMATCH", "file": relative.as_posix(), "expected": item["checksum"], "actual": checksum})
        expected_columns = [*configured[entity]["columns"], "_load_id", "_generation_id"]
        try:
            if item["format"] == "csv":
                with path.open(newline="", encoding="utf-8") as handle:
                    reader = csv.reader(handle)
                    header = next(reader)
                    row_count = sum(1 for _ in reader)
                actual_columns = header
            elif item["format"] == "parquet":
                try:
                    import pyarrow.parquet as pq
                except ImportError as exc:
                    raise RuntimeError("Parquet validation requires pyarrow") from exc
                parquet = pq.ParquetFile(path)
                actual_columns = parquet.schema_arrow.names
                row_count = parquet.metadata.num_rows
            else:
                findings.append({"code": "UNEXPECTED_EXTENSION", "file": relative.as_posix()})
                continue
        except Exception as exc:
            findings.append({"code": "UNREADABLE_FILE", "file": relative.as_posix(), "error": str(exc)})
            continue
        if actual_columns != expected_columns:
            findings.append({"code": "COLUMN_MISMATCH", "file": relative.as_posix(), "expected": expected_columns, "actual": actual_columns})
        if row_count != item["row_count"]:
            findings.append({"code": "ROW_COUNT_MISMATCH", "file": relative.as_posix(), "expected": item["row_count"], "actual": row_count})
        parts = relative.parts
        if entity in {"reservations", "payments", "cancellations", "refunds", "reservation_guests", "folio_charges", "stays", "channel_bookings", "housekeeping_events", "web_booking_events", "room_inventory", "daily_rates", "property_daily_metrics", "guest_preferences"}:
            if not any(part.startswith("year=") for part in parts) or not any(part.startswith("month=") for part in parts):
                findings.append({"code": "PARTITION_MISSING", "file": relative.as_posix()})
            if item["format"] == "csv" and not any(part.startswith("day=") for part in parts):
                findings.append({"code": "DAY_PARTITION_MISSING", "file": relative.as_posix()})
        verified_files += 1
        verified_rows += row_count
    return {
        "status": PASS if not findings else FAIL,
        "generation_id": manifest.get("generation_id"),
        "verified_files": verified_files,
        "verified_rows": verified_rows,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    result = validate(data_dir, (args.manifest or data_dir / "manifest.json").resolve())
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
