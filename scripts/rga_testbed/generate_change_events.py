#!/usr/bin/env python3
"""Generate deterministic CDC events over an existing RGA synthetic dataset."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "artifacts" / "rga_testbed"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_cdc"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--events-per-type", type=int, default=10)
    parser.add_argument("--effective-date", default=None)
    return parser.parse_args()


def read_entity(root: Path, entity: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    folder = root / "csv" / entity
    for path in sorted(folder.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _event_id(generation_id: str, entity: str, business_key: str, operation: str) -> str:
    payload = f"{generation_id}|{entity}|{business_key}|{operation}".encode()
    return "cdc_" + hashlib.sha256(payload).hexdigest()[:20]


def build_events(input_root: Path, events_per_type: int, effective_date: date) -> list[dict[str, Any]]:
    if events_per_type < 1:
        raise ValueError("events-per-type must be positive")
    manifest = json.loads((input_root / "manifest.json").read_text(encoding="utf-8"))
    generation_id = manifest["generation_id"]
    policies = read_entity(input_root, "policies")
    premiums = read_entity(input_root, "premiums")
    claims = read_entity(input_root, "claims")
    treaties = {row["treaty_id"]: row for row in read_entity(input_root, "treaties")}

    events: list[dict[str, Any]] = []

    active = [row for row in policies if row["policy_status"] == "ACTIVE"][:events_per_type]
    for row in active:
        after = dict(row)
        after["policy_status"] = "LAPSED"
        events.append(
            {
                "event_id": _event_id(generation_id, "policies", row["policy_id"], "UPDATE"),
                "entity": "policies",
                "operation": "UPDATE",
                "business_key": row["policy_id"],
                "effective_at": effective_date.isoformat(),
                "scenario": "policy_status_change",
                "semantic_grain": None,
                "before": row,
                "after": after,
            }
        )

    for row in premiums[:events_per_type]:
        after = dict(row)
        corrected_gross = round(float(row["gross_premium"]) * 1.05, 2)
        treaty = treaties[row["treaty_id"]]
        after["gross_premium"] = f"{corrected_gross:.2f}"
        after["ceded_premium"] = f"{round(corrected_gross * float(treaty['ceded_share_pct']), 2):.2f}"
        events.append(
            {
                "event_id": _event_id(generation_id, "premiums", row["premium_txn_id"], "UPDATE"),
                "entity": "premiums",
                "operation": "UPDATE",
                "business_key": row["premium_txn_id"],
                "effective_at": effective_date.isoformat(),
                "scenario": "premium_correction",
                "semantic_grain": {
                    "cedant_id": row["cedant_id"],
                    "treaty_id": row["treaty_id"],
                    "period_month": row["accounting_date"][:7] + "-01",
                },
                "before": row,
                "after": after,
            }
        )

    claimed_policy_ids = {row["policy_id"] for row in claims}
    late_candidates = [row for row in policies if row["policy_id"] not in claimed_policy_ids][:events_per_type]
    for index, policy in enumerate(late_candidates, 1):
        event_date = effective_date - timedelta(days=60 + index)
        reported_date = effective_date
        treaty = treaties[policy["treaty_id"]]
        gross = round(float(policy["sum_assured"]) * 0.75, 2)
        ceded = round(gross * float(treaty["ceded_share_pct"]), 2)
        claim_id = f"LATE_{policy['policy_id']}"
        after = {
            "claim_id": claim_id,
            "policy_id": policy["policy_id"],
            "treaty_id": policy["treaty_id"],
            "insured_id": policy["insured_id"],
            "event_date": event_date.isoformat(),
            "reported_date": reported_date.isoformat(),
            "claim_status": "OPEN",
            "cause_code": "LATE_REPORTED",
            "claim_amount": f"{gross:.2f}",
            "ceded_claim_amount": f"{ceded:.2f}",
            "currency_code": policy["currency_code"],
            "_generation_id": generation_id,
        }
        events.append(
            {
                "event_id": _event_id(generation_id, "claims", claim_id, "INSERT"),
                "entity": "claims",
                "operation": "INSERT",
                "business_key": claim_id,
                "effective_at": effective_date.isoformat(),
                "scenario": "late_arriving_claim",
                "semantic_grain": {
                    "cedant_id": policy["cedant_id"],
                    "treaty_id": policy["treaty_id"],
                    "period_month": event_date.replace(day=1).isoformat(),
                },
                "before": None,
                "after": after,
            }
        )
    return events


def validate_events(events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [event["event_id"] for event in events]
    if len(ids) != len(set(ids)):
        errors.append("duplicate CDC event IDs")
    for event in events:
        if event["operation"] == "UPDATE" and (not event.get("before") or not event.get("after")):
            errors.append(f"update event missing before/after: {event['event_id']}")
        if event["operation"] == "INSERT" and event.get("before") is not None:
            errors.append(f"insert event has before image: {event['event_id']}")
        if event["scenario"] in {"premium_correction", "late_arriving_claim"}:
            grain = event.get("semantic_grain")
            if not isinstance(grain, dict):
                errors.append(f"semantic-changing event missing semantic_grain: {event['event_id']}")
            else:
                required = {"cedant_id", "treaty_id", "period_month"}
                if not required.issubset(grain):
                    errors.append(f"semantic_grain missing required keys: {event['event_id']}")
                if grain.get("period_month") and not str(grain["period_month"]).endswith("-01"):
                    errors.append(f"semantic_grain period_month is not month grain: {event['event_id']}")

        if event["scenario"] == "premium_correction":
            before = event["before"]
            after = event["after"]
            if float(after["gross_premium"]) <= float(before["gross_premium"]):
                errors.append(f"premium correction did not increase gross premium: {event['event_id']}")
            if float(after["ceded_premium"]) > float(after["gross_premium"]):
                errors.append(f"ceded premium exceeds gross premium: {event['event_id']}")
            grain = event.get("semantic_grain") or {}
            if grain.get("cedant_id") != after.get("cedant_id") or grain.get("treaty_id") != after.get("treaty_id"):
                errors.append(f"premium semantic_grain key mismatch: {event['event_id']}")
            expected_month = str(after.get("accounting_date", ""))[:7] + "-01"
            if grain.get("period_month") != expected_month:
                errors.append(f"premium semantic_grain month mismatch: {event['event_id']}")
        if event["scenario"] == "late_arriving_claim":
            after = event["after"]
            grain = event.get("semantic_grain") or {}
            expected_month = str(after.get("event_date", ""))[:7] + "-01"
            if grain.get("period_month") != expected_month:
                errors.append(f"late claim semantic_grain month mismatch: {event['event_id']}")
            if after["event_date"] >= after["reported_date"]:
                errors.append(f"late claim is not late: {event['event_id']}")
            if float(after["ceded_claim_amount"]) > float(after["claim_amount"]):
                errors.append(f"ceded claim exceeds gross claim: {event['event_id']}")
    return errors


def generate(input_root: Path, output: Path, events_per_type: int, effective_date: date | None = None) -> dict[str, Any]:
    manifest = json.loads((input_root / "manifest.json").read_text(encoding="utf-8"))
    resolved_date = effective_date or (date.fromisoformat(manifest["reference_date"]) + timedelta(days=1))
    events = build_events(input_root, events_per_type, resolved_date)
    errors = validate_events(events)
    output.mkdir(parents=True, exist_ok=True)
    jsonl = output / "change_events.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    counts: dict[str, int] = {}
    for event in events:
        key = event["scenario"]
        counts[key] = counts.get(key, 0) + 1
    result = {
        "status": "PASS" if not errors else "FAIL",
        "source_generation_id": manifest["generation_id"],
        "effective_date": resolved_date.isoformat(),
        "event_count": len(events),
        "scenario_counts": counts,
        "errors": errors,
        "file": jsonl.name,
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    args = parse_args()
    result = generate(
        args.input,
        args.output,
        args.events_per_type,
        date.fromisoformat(args.effective_date) if args.effective_date else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
