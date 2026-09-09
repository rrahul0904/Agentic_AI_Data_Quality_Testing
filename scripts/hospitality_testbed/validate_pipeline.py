#!/usr/bin/env python3
"""Run deterministic RAW-equivalent data-quality rules over generated source files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lib import FAIL, PASS, ROOT, evidence_path, load_yaml, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "hospitality" / "manifest.json")
    parser.add_argument("--json-output", type=Path, default=evidence_path("quality.json"))
    return parser.parse_args()


def iter_rows(path: Path, fmt: str) -> Iterable[dict[str, Any]]:
    if fmt == "csv":
        with path.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)
    else:
        import pyarrow.parquet as pq
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=10_000):
            yield from batch.to_pylist()


def load_entities(manifest: dict[str, Any], root: Path) -> dict[str, list[dict[str, Any]]]:
    entities: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in manifest["files"]:
        entities[item["entity"]].extend(iter_rows(root / item["file"], item["format"]))
    return dict(entities)


def finding(name: str, failed: int, evidence: Any = None) -> dict[str, Any]:
    return {"rule": name, "status": PASS if failed == 0 else FAIL, "failed_rows": failed, "evidence": evidence or []}


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        rows = load_entities(manifest, args.manifest.parent)
        ids = {entity: {str(row.get(key)) for row in values if row.get(key) not in {None, ""}} for entity, values, key in (
            ("hotels", rows["hotels"], "hotel_id"), ("rooms", rows["rooms"], "room_id"), ("guests", rows["guests"], "guest_id"),
            ("reservations", rows["reservations"], "reservation_id"), ("payments", rows["payments"], "payment_id"),
        )}
        checks = []
        for entity, key in (("hotels", "hotel_id"), ("rooms", "room_id"), ("guests", "guest_id"), ("reservations", "reservation_id"), ("payments", "payment_id"), ("stays", "stay_id")):
            values = [str(row.get(key) or "") for row in rows.get(entity, [])]
            checks.append(finding(f"{entity}_business_key_not_null", sum(not value for value in values)))
            checks.append(finding(f"{entity}_business_key_unique", len(values) - len(set(values))))
        reservations = rows["reservations"]
        checks.extend((
            finding("reservation_dates_valid", sum(date.fromisoformat(str(row["checkout_date"])[:10]) < date.fromisoformat(str(row["checkin_date"])[:10]) for row in reservations)),
            finding("reservation_amount_non_negative", sum(float(row["total_amount"]) < 0 for row in reservations)),
            finding("reservation_hotel_exists", sum(str(row["hotel_id"]) not in ids["hotels"] for row in reservations)),
            finding("reservation_guest_exists", sum(str(row["guest_id"]) not in ids["guests"] for row in reservations)),
            finding("reservation_room_exists", sum(str(row["room_id"]) not in ids["rooms"] for row in reservations)),
            finding("payment_reservation_exists", sum(str(row["reservation_id"]) not in ids["reservations"] for row in rows["payments"])),
            finding("payment_amount_non_negative", sum(float(row["amount"]) < 0 for row in rows["payments"])),
            finding("inventory_capacity", sum(int(row["occupied_rooms"]) > int(row["available_rooms"]) for row in rows["room_inventory"])),
        ))
        payment_amount = {str(row["payment_id"]): float(row["amount"]) for row in rows["payments"]}
        checks.append(finding("refund_not_greater_than_payment", sum(float(row["amount"]) > payment_amount.get(str(row["payment_id"]), -1) for row in rows["refunds"])))
        configured_rule_count = len(load_yaml("hospitality_quality.yml")["rules"])
        result = {"status": PASS if all(item["status"] == PASS for item in checks) else FAIL, "scope": "LOCAL_GENERATED_DATA", "generation_id": manifest["generation_id"], "configured_rule_count": configured_rule_count, "executed_rule_count": len(checks), "checks": checks}
    except Exception as exc:
        result = {"status": FAIL, "scope": "LOCAL_GENERATED_DATA", "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
