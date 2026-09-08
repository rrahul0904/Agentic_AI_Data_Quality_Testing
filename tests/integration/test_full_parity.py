from __future__ import annotations

import json
from pathlib import Path

from agentic_data_platform.tools.builtin import build_tool_registry

ROOT = Path(__file__).resolve().parents[2]


def test_altimate_and_airflow_ledgers_have_no_local_blockers():
    for name in ("ALTIMATE_FULL_PARITY_LEDGER.json", "AIRFLOW_CAPABILITY_LEDGER.json"):
        data = json.loads((ROOT / "specs" / name).read_text())
        assert data["status_counts"].get("MISSING", 0) == 0
        assert data["status_counts"].get("PARTIAL", 0) == 0


def test_altimate_tool_evidence_resolves_to_registered_tools():
    data = json.loads((ROOT / "specs" / "ALTIMATE_FULL_PARITY_LEDGER.json").read_text())
    names = {item.name for item in build_tool_registry().definitions()}
    missing = [
        item["our_tool_name"]
        for item in data["entries"]
        if item.get("our_tool_name") and item["our_tool_name"] not in names
    ]
    assert missing == []


def test_required_acceptance_artifacts_exist():
    required = (
        "specs/CURRENT_IMPLEMENTATION_BASELINE.md",
        "specs/CURRENT_IMPLEMENTATION_BASELINE.json",
        "specs/ALTIMATE_REFERENCE_SNAPSHOT.json",
        "specs/ALTIMATE_FULL_PARITY_LEDGER.json",
        "specs/AIRFLOW_CAPABILITY_LEDGER.json",
        "scripts/check_parity_gate.py",
        "scripts/altimate_reference_inventory.py",
        "scripts/altimate_parity_evidence.py",
    )
    for path in required:
        assert (ROOT / path).is_file(), path
