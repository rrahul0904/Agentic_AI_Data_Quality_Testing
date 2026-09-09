from __future__ import annotations

import json
from pathlib import Path

from scripts.check_capability_superiority import load_ledger, validate
from scripts.generate_coco_certification import generate


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


def test_capabilities_are_split_into_coco_and_extension_certification_tracks():
    payload = load_ledger(LEDGER)
    result = validate(payload)

    assert result["status"] == "PASS", result["errors"]
    assert result["by_classification"]["COCO_CORE"] > 0
    assert result["by_classification"]["COCO_WORKFLOW"] > 0
    assert result["by_classification"]["ADE_EXTENSION"] > 0

    for item in payload["capabilities"]:
        if item["classification"] == "ADE_EXTENSION":
            assert item["release_blocking"] is False
            assert item["certification_track"] == "SNOWFLAKE_EXTENSION_CERTIFICATION"
        else:
            assert item["release_blocking"] is True
            assert item["certification_track"] == "COCO_PARITY_CERTIFICATION"


def test_coco_parity_gate_ignores_extension_live_certification():
    payload = load_ledger(LEDGER)
    extensions = [item for item in payload["capabilities"] if item["classification"] == "ADE_EXTENSION"]
    assert extensions

    for item in extensions:
        item["ade_current"] = "gap"
        item["certification"] = {"local": "NOT_CERTIFIED", "live": "NOT_RUN_EXTERNAL"}

    result = validate(payload, scope="coco", require_coco_parity=True)
    assert all("cortex_search" not in blocker for blocker in result["release_blockers"])
    assert all("ml.gpu_jobs" not in blocker for blocker in result["release_blockers"])
    assert result["release_blockers"]


def test_certification_reports_are_separate_and_honest(tmp_path):
    coco_path, extension_path = generate(LEDGER, tmp_path)
    coco = json.loads(coco_path.read_text())
    extensions = json.loads(extension_path.read_text())

    assert coco["scope"] == "coco"
    assert extensions["scope"] == "extensions"
    assert all(item["classification"] != "ADE_EXTENSION" for item in coco["capabilities"])
    assert all(item["classification"] == "ADE_EXTENSION" for item in extensions["capabilities"])
    assert all(item["release_blocking"] is False for item in extensions["capabilities"])
    assert (tmp_path / "coco_parity_report.md").exists()
    assert (tmp_path / "snowflake_extensions_report.md").exists()
