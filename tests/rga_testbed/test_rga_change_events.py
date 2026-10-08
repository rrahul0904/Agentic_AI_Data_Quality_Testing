from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_change_events_cover_updates_and_late_claims(tmp_path: Path):
    generator = load_module("rga_base_for_cdc", ROOT / "scripts" / "rga_testbed" / "generate_data.py")
    cdc = load_module("rga_cdc", ROOT / "scripts" / "rga_testbed" / "generate_change_events.py")
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    base = tmp_path / "base"
    generator.build_dataset(config, "tiny", 42, date(2026, 9, 1), base, policy_override=120)
    output = tmp_path / "cdc"
    result = cdc.generate(base, output, events_per_type=5)
    assert result["status"] == "PASS"
    assert result["event_count"] == 15
    assert result["scenario_counts"] == {
        "late_arriving_claim": 5,
        "policy_status_change": 5,
        "premium_correction": 5,
    }
    lines = [json.loads(line) for line in (output / "change_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 15
    assert {event["operation"] for event in lines} == {"UPDATE", "INSERT"}


def test_cdc_events_are_deterministic(tmp_path: Path):
    generator = load_module("rga_base_for_cdc_repeat", ROOT / "scripts" / "rga_testbed" / "generate_data.py")
    cdc = load_module("rga_cdc_repeat", ROOT / "scripts" / "rga_testbed" / "generate_change_events.py")
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    base = tmp_path / "base"
    generator.build_dataset(config, "tiny", 7, date(2026, 9, 1), base, policy_override=80)
    left = tmp_path / "left"
    right = tmp_path / "right"
    assert cdc.generate(base, left, 3) == cdc.generate(base, right, 3)
    assert (left / "change_events.jsonl").read_text(encoding="utf-8") == (
        right / "change_events.jsonl"
    ).read_text(encoding="utf-8")


def test_late_claim_and_premium_business_invariants(tmp_path: Path):
    generator = load_module("rga_base_for_cdc_rules", ROOT / "scripts" / "rga_testbed" / "generate_data.py")
    cdc = load_module("rga_cdc_rules", ROOT / "scripts" / "rga_testbed" / "generate_change_events.py")
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    base = tmp_path / "base"
    generator.build_dataset(config, "tiny", 9, date(2026, 9, 1), base, policy_override=100)
    events = cdc.build_events(base, 4, date(2026, 9, 2))
    assert cdc.validate_events(events) == []
    for event in events:
        if event["scenario"] == "late_arriving_claim":
            assert event["after"]["event_date"] < event["after"]["reported_date"]
        if event["scenario"] == "premium_correction":
            assert float(event["after"]["ceded_premium"]) <= float(event["after"]["gross_premium"])
