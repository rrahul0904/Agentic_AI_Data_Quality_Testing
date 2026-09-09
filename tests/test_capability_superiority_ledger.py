from __future__ import annotations

import json
from pathlib import Path

from scripts.check_capability_superiority import load_ledger, validate


LEDGER = Path("specs/ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json")


def test_reference_capability_ledger_is_complete_and_well_formed():
    payload = load_ledger(LEDGER)
    result = validate(payload)

    assert result["status"] == "PASS", result["errors"]
    assert result["capability_count"] >= 50
    assert result["source_count"] >= 15
    assert result["target_score"] == 2
    assert result["errors"] == []


def test_every_reference_capability_has_two_superiority_advantages():
    payload = json.loads(LEDGER.read_text())
    for item in payload["capabilities"]:
        assert item["target_score"] == 2
        assert len(item["superiority_advantages"]) >= 2
        assert item["acceptance"].strip()


def test_every_reference_capability_is_owned_by_a_delivery_phase():
    payload = json.loads(LEDGER.read_text())
    assert {item["phase"] for item in payload["capabilities"]} <= {"P0", "P1", "P2"}
    assert {"P0", "P1", "P2"} <= {item["phase"] for item in payload["capabilities"]}
