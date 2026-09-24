from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    return load_module(
        "rga_cdc_validate_test",
        ROOT / "scripts" / "rga_testbed" / "validate_cdc_application.py",
    )


def test_cdc_validation_maps_supported_scenarios_to_raw_checks():
    module = _module()

    policy = module.event_check(
        {
            "scenario": "policy_status_change",
            "after": {"policy_id": "P1", "policy_status": "LAPSED"},
        }
    )
    assert policy["table"] == "RAW.POLICIES"
    assert policy["key_column"] == "POLICY_ID"
    assert policy["fields"] == {"POLICY_STATUS": "LAPSED"}

    premium = module.event_check(
        {
            "scenario": "premium_correction",
            "after": {
                "premium_txn_id": "PR1",
                "gross_premium": "105.00",
                "ceded_premium": "52.50",
            },
        }
    )
    assert premium["table"] == "RAW.PREMIUMS"
    assert premium["fields"]["GROSS_PREMIUM"] == "105.00"

    claim = module.event_check(
        {
            "scenario": "late_arriving_claim",
            "after": {
                "claim_id": "C1",
                "event_date": "2026-01-01",
                "reported_date": "2026-03-01",
                "claim_status": "OPEN",
                "claim_amount": "1000.00",
                "ceded_claim_amount": "500.00",
            },
        }
    )
    assert claim["table"] == "RAW.CLAIMS"
    assert claim["fields"]["REPORTED_DATE"] == "2026-03-01"


def test_cdc_validation_rejects_unsupported_scenario():
    module = _module()
    try:
        module.event_check({"scenario": "unknown", "after": {}})
    except ValueError as exc:
        assert "Unsupported CDC scenario" in str(exc)
    else:
        raise AssertionError("unsupported CDC scenarios must fail closed")


def test_cdc_validation_dry_run_reports_scenario_counts(tmp_path: Path):
    module = _module()
    events = [
        {
            "event_id": "e1",
            "scenario": "policy_status_change",
            "after": {"policy_id": "P1", "policy_status": "LAPSED"},
        },
        {
            "event_id": "e2",
            "scenario": "premium_correction",
            "after": {
                "premium_txn_id": "PR1",
                "gross_premium": "105.00",
                "ceded_premium": "52.50",
            },
        },
        {
            "event_id": "e3",
            "scenario": "late_arriving_claim",
            "after": {
                "claim_id": "C1",
                "event_date": "2026-01-01",
                "reported_date": "2026-03-01",
                "claim_status": "OPEN",
                "claim_amount": "1000.00",
                "ceded_claim_amount": "500.00",
            },
        },
    ]
    path = tmp_path / "change_events.jsonl"
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    loaded = module.load_events(path)
    report = module.dry_run_payload(loaded, "RGA_SYNTHETIC_TESTBED")

    assert report["status"] == "DRY_RUN"
    assert report["event_count"] == 3
    assert report["scenario_counts"] == {
        "policy_status_change": 1,
        "premium_correction": 1,
        "late_arriving_claim": 1,
    }
    assert any("audit" in item.lower() for item in report["acceptance"])


def test_cdc_audit_cardinality_requires_exactly_one_applied_row():
    module = _module()
    assert module.audit_record_errors(None) == ["audit record is missing"]
    assert module.audit_record_errors({"count": 1, "statuses": {"APPLIED"}}) == []

    duplicate = module.audit_record_errors(
        {"count": 2, "statuses": {"APPLIED"}}
    )
    assert any("row count expected 1" in error for error in duplicate)

    mixed = module.audit_record_errors(
        {"count": 2, "statuses": {"APPLIED", "FAILED"}}
    )
    assert any("row count expected 1" in error for error in mixed)
    assert any("expected only APPLIED" in error for error in mixed)
