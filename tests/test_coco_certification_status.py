from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.certification import coco_certification_status


def _write(root, relative, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_certification_status_separates_implementation_ci_live_and_superiority(tmp_path):
    _write(
        tmp_path,
        "specs/ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json",
        {
            "benchmark": "fixture",
            "target_matrix": {"version": "fixture-v1"},
            "capabilities": [
                {
                    "id": "core.ready",
                    "reference": "ready",
                    "phase": "P1",
                    "ade_current": "implemented_on_branch",
                    "certification_track": "COCO_PARITY_CERTIFICATION",
                },
                {
                    "id": "core.open",
                    "reference": "open",
                    "phase": "P2",
                    "ade_current": "partial",
                    "acceptance": "finish it",
                    "certification_track": "COCO_PARITY_CERTIFICATION",
                },
                {
                    "id": "extension.live",
                    "reference": "extension",
                    "phase": "P2",
                    "ade_current": "implemented_on_branch",
                    "certification_track": "ADE_EXTENSION_ASSURANCE",
                },
            ],
        },
    )
    _write(
        tmp_path,
        "specs/COCO_GOLDEN_SCENARIOS.json",
        {"scenarios": [{"id": "GS01", "title": "one", "expected": "PASS"}]},
    )

    result = coco_certification_status(tmp_path)

    assert result["status"] == "PASS"
    assert result["coco_capability_count"] == 2
    assert result["extension_capability_count"] == 1
    assert result["implemented_coco_count"] == 1
    assert result["unresolved_coco_count"] == 1
    assert result["unresolved_coco_capabilities"][0]["id"] == "core.open"
    assert result["claims"] == {
        "implementation_parity_ready": False,
        "exact_head_ci_certified": False,
        "live_external_certified": False,
        "superiority_certified": False,
    }
    assert result["exact_head_evidence"] is None
    assert result["status_fingerprint"]


def test_checked_in_report_is_evidence_but_never_implies_live_or_superiority(tmp_path):
    _write(
        tmp_path,
        "specs/ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json",
        {
            "capabilities": [
                {
                    "id": "core.ready",
                    "ade_current": "implemented",
                    "certification_track": "COCO_PARITY_CERTIFICATION",
                }
            ]
        },
    )
    _write(tmp_path, "specs/COCO_GOLDEN_SCENARIOS.json", {"scenarios": []})
    _write(
        tmp_path,
        "reports/certification/coco_certification_report.json",
        {
            "head_sha": "abc123",
            "local_ci_certified": True,
            "coco_parity_complete": True,
            "live_external_certified": True,
            "superiority_certified": True,
            "golden_scenarios": {"status": "PASS", "passed": 8, "failed": 0},
            "certification_fingerprint": "report-fingerprint",
        },
    )

    result = coco_certification_status(tmp_path)

    assert result["claims"]["implementation_parity_ready"] is True
    assert result["claims"]["exact_head_ci_certified"] is True
    assert result["claims"]["live_external_certified"] is False
    assert result["claims"]["superiority_certified"] is False
    assert result["exact_head_evidence"]["head_sha"] == "abc123"


def test_operator_api_exposes_truthful_coco_status():
    client = TestClient(create_app())
    response = client.get("/api/v1/certification/coco")

    assert response.status_code == 200
    payload = response.json()
    assert payload["capability_count"] == 69
    assert payload["coco_capability_count"] > 0
    assert payload["extension_capability_count"] > 0
    assert len(payload["golden_scenario_definitions"]) == 8
    assert payload["claims"]["live_external_certified"] is False
    assert payload["claims"]["superiority_certified"] is False
    assert payload["truthfulness"]["missing_ci_report_never_treated_as_green"] is True
