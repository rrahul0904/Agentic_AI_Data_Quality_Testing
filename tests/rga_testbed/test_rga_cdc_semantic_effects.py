from __future__ import annotations

import importlib.util
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
        "rga_cdc_semantic_effects_test",
        ROOT / "scripts" / "rga_testbed" / "validate_cdc_semantic_effects.py",
    )


def test_cdc_semantic_expectations_aggregate_same_grain_exactly():
    module = _module()
    events = [
        {
            "event_id": "premium-1",
            "scenario": "premium_correction",
            "semantic_grain": {
                "cedant_id": "CED-1",
                "treaty_id": "TRT-1",
                "period_month": "2026-01-01",
            },
            "before": {
                "gross_premium": "100.00",
                "ceded_premium": "50.00",
            },
            "after": {
                "gross_premium": "105.00",
                "ceded_premium": "52.50",
            },
        },
        {
            "event_id": "premium-2",
            "scenario": "premium_correction",
            "semantic_grain": {
                "cedant_id": "CED-1",
                "treaty_id": "TRT-1",
                "period_month": "2026-01-01",
            },
            "before": {
                "gross_premium": "200.00",
                "ceded_premium": "100.00",
            },
            "after": {
                "gross_premium": "210.00",
                "ceded_premium": "105.00",
            },
        },
        {
            "event_id": "claim-1",
            "scenario": "late_arriving_claim",
            "semantic_grain": {
                "cedant_id": "CED-1",
                "treaty_id": "TRT-1",
                "period_month": "2026-01-01",
            },
            "after": {
                "claim_amount": "1000.00",
                "ceded_claim_amount": "600.00",
            },
        },
        {
            "event_id": "policy-1",
            "scenario": "policy_status_change",
            "semantic_grain": None,
            "before": {"policy_status": "ACTIVE"},
            "after": {"policy_status": "LAPSED"},
        },
    ]

    expectations = module.build_expectations(events)
    assert len(expectations) == 1
    item = expectations[0]
    assert item["grain"] == {
        "cedant_id": "CED-1",
        "treaty_id": "TRT-1",
        "period_month": "2026-01-01",
    }
    assert item["deltas"] == {
        "gross_premium": "15.00",
        "ceded_premium": "7.50",
        "gross_claim_amount": "1000.00",
        "ceded_claim_amount": "600.00",
        "claim_count": 1,
    }
    assert item["event_ids"] == ["claim-1", "premium-1", "premium-2"]
    assert item["scenarios"] == ["late_arriving_claim", "premium_correction"]


def test_expected_post_adds_one_cdc_delta_to_baseline():
    module = _module()
    baseline = {
        "row_exists": True,
        "gross_premium": "1000.00",
        "ceded_premium": "500.00",
        "gross_claim_amount": "200.00",
        "ceded_claim_amount": "100.00",
        "claim_count": 3,
    }
    deltas = {
        "gross_premium": "15.00",
        "ceded_premium": "7.50",
        "gross_claim_amount": "1000.00",
        "ceded_claim_amount": "600.00",
        "claim_count": 1,
    }
    expected = module.expected_post(baseline, deltas)
    assert expected == {
        "gross_premium": "1015.00",
        "ceded_premium": "507.50",
        "gross_claim_amount": "1200.00",
        "ceded_claim_amount": "700.00",
        "claim_count": 4,
    }


def test_policy_only_events_do_not_invent_mart_metric_effects():
    module = _module()
    events = [
        {
            "event_id": "policy-1",
            "scenario": "policy_status_change",
            "semantic_grain": None,
            "after": {"policy_status": "LAPSED"},
        }
    ]
    try:
        module.build_expectations(events)
    except ValueError as exc:
        assert "No CDC events have semantic metric effects" in str(exc)
    else:
        raise AssertionError("policy-only CDC must not fabricate a MART delta")


def test_semantic_expectation_requires_grain_for_metric_changing_event():
    module = _module()
    events = [
        {
            "event_id": "premium-1",
            "scenario": "premium_correction",
            "before": {"gross_premium": "100.00", "ceded_premium": "50.00"},
            "after": {"gross_premium": "105.00", "ceded_premium": "52.50"},
        }
    ]
    try:
        module.build_expectations(events)
    except ValueError as exc:
        assert "missing semantic_grain" in str(exc)
    else:
        raise AssertionError("metric-changing CDC without semantic grain must fail")


def test_semantic_effect_dry_run_documents_current_model_boundary():
    module = _module()
    events = [
        {
            "event_id": "claim-1",
            "scenario": "late_arriving_claim",
            "semantic_grain": {
                "cedant_id": "CED-1",
                "treaty_id": "TRT-1",
                "period_month": "2026-01-01",
            },
            "after": {
                "claim_amount": "1000.00",
                "ceded_claim_amount": "500.00",
            },
        }
    ]
    report = module.dry_run_payload(events, "RGA_SYNTHETIC_TESTBED")
    assert report["status"] == "DRY_RUN"
    assert report["grain_count"] == 1
    assert "Policy lapse has no MART metric delta assertion" in report["note"]
