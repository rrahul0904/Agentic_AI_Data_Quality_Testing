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


def test_microsoft_consumers_share_semantic_view_and_are_feature_gated(tmp_path: Path):
    module = load_module(
        "rga_microsoft",
        ROOT / "scripts" / "rga_testbed" / "generate_microsoft_consumer_pack.py",
    )
    contract = module.build_contract("RGA_SYNTHETIC_TESTBED")
    assert contract["semantic_view"] == "RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE"
    assert contract["protocol"] == "XMLA"
    assert contract["availability"] == "account_entitlement_or_feature_gate_required"
    assert "Detect endpoint availability" in contract["availability_policy"]
    assert contract["power_bi"]["required_connection_mode"] == "live"
    assert contract["excel"]["required_connection_mode"] == "live_xmla"
    assert contract["power_bi"]["must_not_reimplement"] == contract["excel"]["must_not_reimplement"]


def test_consumer_pack_does_not_claim_endpoint_is_enabled(tmp_path: Path):
    module = load_module(
        "rga_microsoft_files",
        ROOT / "scripts" / "rga_testbed" / "generate_microsoft_consumer_pack.py",
    )
    files = module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    assert len(files) == 3
    contract = json.loads((tmp_path / "consumer_contract.json").read_text(encoding="utf-8"))
    template = (tmp_path / "xmla_setup.template.sql").read_text(encoding="utf-8")
    checklist = (tmp_path / "PARITY_CHECKLIST.md").read_text(encoding="utf-8")
    assert contract["availability"] == "account_entitlement_or_feature_gate_required"
    assert "Detect endpoint availability" in contract["availability_policy"]
    assert "FEATURE GATE" in template
    assert "account" in checklist.lower()
    assert "Power BI API evidence is valid only" in checklist
    assert "<XMLA_ENDPOINT_NAME>" in template
    assert "ADD SEMANTIC VIEW RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE" in template
    assert "Live Connection" in checklist
    assert "Direct-connection fallback is connectivity evidence, not semantic-parity certification" in checklist


def test_parity_contract_covers_core_governed_metrics():
    module = load_module(
        "rga_microsoft_metrics",
        ROOT / "scripts" / "rga_testbed" / "generate_microsoft_consumer_pack.py",
    )
    contract = module.build_contract("RGA_SYNTHETIC_TESTBED")
    metrics = set(contract["parity_metrics"])
    assert {
        "TOTAL_GROSS_PREMIUM",
        "TOTAL_CEDED_PREMIUM",
        "TOTAL_CEDED_CLAIMS",
        "TOTAL_EXPOSURE",
        "CEDED_LOSS_RATIO",
        "CEDED_PREMIUM_RATE",
    } <= metrics
