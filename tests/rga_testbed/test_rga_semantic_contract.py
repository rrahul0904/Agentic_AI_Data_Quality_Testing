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


def test_canonical_contract_is_single_metric_source(tmp_path: Path):
    contract_module = load_module(
        "rga_semantic_contract_test",
        ROOT / "scripts" / "rga_testbed" / "semantic_contract.py",
    )
    semantic_module = load_module(
        "rga_semantic_from_contract_test",
        ROOT / "scripts" / "rga_testbed" / "generate_semantic_view.py",
    )
    microsoft_module = load_module(
        "rga_microsoft_from_contract_test",
        ROOT / "scripts" / "rga_testbed" / "generate_microsoft_consumer_pack.py",
    )
    benchmark_module = load_module(
        "rga_benchmark_from_contract_test",
        ROOT / "scripts" / "rga_testbed" / "generate_benchmark_pack.py",
    )

    contract = contract_module.load_semantic_contract()
    governed_metrics = set(contract_module.metric_names(contract))

    semantic = semantic_module.build_semantic_spec("RGA_SYNTHETIC_TESTBED")
    semantic_metrics = {item["name"] for item in semantic["tables"][0]["metrics"]}
    assert semantic_metrics == governed_metrics

    microsoft = microsoft_module.build_contract("RGA_SYNTHETIC_TESTBED")
    assert set(microsoft["parity_metrics"]) == governed_metrics

    benchmark = benchmark_module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    benchmark_metrics = {
        metric
        for query in benchmark["queries"]
        for metric in query["metrics"]
    }
    assert benchmark_metrics <= governed_metrics
    assert benchmark["recommended_concurrency"] == contract["performance"]["concurrency"]
    assert benchmark["measurements"] == contract["performance"]["collect"]


def test_all_consumers_point_to_same_governed_object():
    contract_module = load_module(
        "rga_semantic_contract_consumers_test",
        ROOT / "scripts" / "rga_testbed" / "semantic_contract.py",
    )
    ai_module = load_module(
        "rga_ai_contract_test",
        ROOT / "scripts" / "rga_testbed" / "generate_ai_integration.py",
    )
    microsoft_module = load_module(
        "rga_ms_contract_test",
        ROOT / "scripts" / "rga_testbed" / "generate_microsoft_consumer_pack.py",
    )

    contract = contract_module.load_semantic_contract()
    expected = contract_module.semantic_view_fqn(contract)

    ai = ai_module.build_agent_spec("RGA_SYNTHETIC_TESTBED")
    microsoft = microsoft_module.build_contract("RGA_SYNTHETIC_TESTBED")

    assert ai["tool_resources"]["Reinsurance_Analyst"]["semantic_view"] == expected
    assert microsoft["semantic_view"] == expected
    assert contract["consumers"]["ai"]["allow_unrestricted_sql"] is False
    assert contract["consumers"]["power_bi"]["duplicate_metric_logic_allowed"] is False
    assert contract["consumers"]["excel"]["duplicate_metric_logic_allowed"] is False


def test_contract_rejects_unknown_verified_query_metric():
    contract_module = load_module(
        "rga_semantic_contract_validation_test",
        ROOT / "scripts" / "rga_testbed" / "semantic_contract.py",
    )
    contract = contract_module.load_semantic_contract()
    broken = {**contract, "verified_queries": [dict(contract["verified_queries"][0])]}
    broken["verified_queries"][0]["metrics"] = ["DOES_NOT_EXIST"]

    try:
        contract_module.validate_semantic_contract(broken)
    except ValueError as exc:
        assert "unknown metrics" in str(exc)
    else:
        raise AssertionError("semantic contract validation should reject unknown metrics")
