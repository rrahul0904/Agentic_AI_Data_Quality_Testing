#!/usr/bin/env python3
"""Fail closed until every non-external Altimate parity row is verified."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "specs" / "ALTIMATE_FULL_PARITY_LEDGER.json"
BLOCKING = {"MISSING", "PARTIAL", "STUB", "UNVERIFIED", "FAKE", "BLOCKED_CODE"}
ALLOWED = {"DONE", "PARTIAL", "MISSING", "STUB", "UNVERIFIED", "SKIP_EXTERNAL", "INTENTIONALLY_SUPERSEDED"}


def main() -> int:
    data = json.loads(LEDGER.read_text())
    entries = data.get("entries", [])
    invalid = [item for item in entries if item.get("status") not in ALLOWED]
    if invalid:
        print(f"Parity ledger has {len(invalid)} invalid status values.")
        return 2

    counts = Counter(item["status"] for item in entries)
    blocking = [item for item in entries if item["status"] in BLOCKING]

    print(f"Reference: {data['generated_for_reference']['repository']}@{data['generated_for_reference']['commit']}")
    print(f"Ledger rows: {len(entries)}")
    for status in sorted(ALLOWED):
        print(f"{status:24s} {counts.get(status, 0)}")

    if blocking:
        print("\nPARITY GATE: FAIL")
        print(f"{len(blocking)} non-external capabilities remain incomplete.")
        for item in blocking[:25]:
            print(f"- {item['status']:10s} {item['reference_path']}")
        if len(blocking) > 25:
            print(f"... plus {len(blocking) - 25} more; inspect specs/ALTIMATE_FULL_PARITY_LEDGER.json")
        return 1

    for item in entries:
        if item["status"] == "DONE":
            if not item.get("our_path") or not item.get("our_symbol") or not item.get("tests"):
                print(f"PARITY GATE: FAIL - DONE row lacks implementation/test evidence: {item['reference_path']}")
                return 3

    print("\nPARITY GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
