#!/usr/bin/env python3
"""Fail CI when required Altimate or Airflow capability evidence is incomplete."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGERS = {
    "altimate": ROOT / "specs" / "ALTIMATE_FULL_PARITY_LEDGER.json",
    "airflow": ROOT / "specs" / "AIRFLOW_CAPABILITY_LEDGER.json",
}
ALLOWED = {"DONE", "PARTIAL", "MISSING", "SKIP_EXTERNAL", "NOT_APPLICABLE"}
BLOCKING = {"MISSING", "PARTIAL"}


def check_ledger(name: str) -> tuple[bool, dict[str, int], list[str]]:
    data = json.loads(LEDGERS[name].read_text())
    entries = data.get("entries", [])
    counts = Counter(str(item.get("status")) for item in entries)
    errors: list[str] = []
    for item in entries:
        status = item.get("status")
        label = item.get("reference_path") or item.get("capability") or "<unknown>"
        if status not in ALLOWED:
            errors.append(f"{label}: invalid status {status!r}")
            continue
        if status in BLOCKING:
            errors.append(f"{label}: blocking status {status}")
        if status in {"DONE", "SKIP_EXTERNAL"}:
            for field in ("our_path", "our_symbol", "tests", "evidence"):
                if not item.get(field):
                    errors.append(f"{label}: {status} lacks {field}")
            our_path = item.get("our_path")
            if our_path and not (ROOT / our_path).exists():
                errors.append(f"{label}: implementation path does not exist: {our_path}")
            for test in item.get("tests") or []:
                if not (ROOT / test).exists():
                    errors.append(f"{label}: test evidence does not exist: {test}")
        if status == "SKIP_EXTERNAL" and not item.get("external_dependency"):
            errors.append(f"{label}: SKIP_EXTERNAL lacks external_dependency")
        if status == "NOT_APPLICABLE" and not item.get("notes") and not item.get("evidence"):
            errors.append(f"{label}: NOT_APPLICABLE lacks architectural justification")
    declared = data.get("status_counts") or {}
    for status in ALLOWED:
        if int(declared.get(status, 0)) != counts.get(status, 0):
            errors.append(f"declared {status}={declared.get(status, 0)} but observed {counts.get(status, 0)}")
    return not errors, dict(counts), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", choices=["altimate", "airflow", "all"], default="all")
    args = parser.parse_args()
    names = list(LEDGERS) if args.ledger == "all" else [args.ledger]
    success = True
    for name in names:
        ok, counts, errors = check_ledger(name)
        print(f"{name.upper()} LEDGER: {'PASS' if ok else 'FAIL'} {counts}")
        for error in errors[:100]:
            print(f"- {error}")
        success = success and ok
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
