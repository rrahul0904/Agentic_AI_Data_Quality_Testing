#!/usr/bin/env python3
"""Validate executable evidence behind Altimate parity rows."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_data_platform.tools.builtin import build_tool_registry

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "specs" / "ALTIMATE_FULL_PARITY_LEDGER.json"


def main() -> int:
    data = json.loads(LEDGER.read_text())
    registry = build_tool_registry()
    registered = {item.name for item in registry.definitions()}
    failures = []
    verified = 0
    for item in data["entries"]:
        tool = item.get("our_tool_name")
        if tool and tool not in registered:
            failures.append({"path": item["reference_path"], "reason": f"tool not registered: {tool}"})
            continue
        if not (ROOT / item["our_path"]).exists():
            failures.append({"path": item["reference_path"], "reason": f"implementation path missing: {item['our_path']}"})
            continue
        if any(not (ROOT / test).exists() for test in item.get("tests", [])):
            failures.append({"path": item["reference_path"], "reason": "test evidence path missing"})
            continue
        verified += 1
    report = {"reference_sha": data["generated_for_reference"]["commit"], "rows": len(data["entries"]), "verified": verified, "failures": failures}
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
