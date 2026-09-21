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


def test_parity_suite_requires_all_four_consumers(tmp_path: Path):
    module = load_module(
        "rga_parity_suite_test",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )
    suite = module.build_suite("RGA_SYNTHETIC_TESTBED")
    assert suite["required_consumers"] == [
        "snowflake_semantic_view",
        "cortex_agent_mcp",
        "power_bi",
        "excel",
    ]
    assert len(suite["cases"]) >= 3
    for case in suite["cases"]:
        assert case["reference"]["semantic_view"] == suite["semantic_view"]
        assert case["ai"]["expected_metrics"] == case["metrics"]
        assert case["power_bi"]["expected_metrics"] == case["metrics"]
        assert case["excel"]["expected_metrics"] == case["metrics"]
        assert case["power_bi"]["allow_local_metric_reimplementation"] is False
        assert case["power_bi"]["capture_api"] == "executeDaxQueries"
        assert case["power_bi"]["dax_file"].endswith(".powerbi.dax")
        assert case["excel"]["allow_local_metric_reimplementation"] is False


def test_parity_suite_emits_reference_sql_for_every_case(tmp_path: Path):
    module = load_module(
        "rga_parity_files_test",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )
    files = module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    manifest = json.loads((tmp_path / "parity_manifest.json").read_text(encoding="utf-8"))
    assert len(files) == (len(manifest["cases"]) * 2) + 1
    for case in manifest["cases"]:
        sql_path = tmp_path / case["reference"]["sql_file"]
        assert sql_path.exists()
        sql = sql_path.read_text(encoding="utf-8")
        assert "semantic_view(" in sql.lower()
        assert "RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE" in sql
        for metric in case["metrics"]:
            assert metric in sql

        dax_path = tmp_path / case["power_bi"]["dax_file"]
        assert dax_path.exists()
        dax = dax_path.read_text(encoding="utf-8")
        assert dax.startswith("EVALUATE\n")
        for dimension in case["dimensions"]:
            assert f"[{dimension}]" in dax
        for metric in case["metrics"]:
            assert f"[{metric}]" in dax


def test_parity_cases_share_metric_and_dimension_contract():
    module = load_module(
        "rga_parity_contract_test",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )
    suite = module.build_suite("RGA_SYNTHETIC_TESTBED")
    for case in suite["cases"]:
        for consumer in ("ai", "power_bi", "excel"):
            assert case[consumer]["expected_metrics"] == case["metrics"]
            assert case[consumer]["expected_dimensions"] == case["dimensions"]
        assert case["acceptance"]["same_metric_definition"] is True
        assert case["acceptance"]["same_dimensional_grain"] is True
        assert case["acceptance"]["same_security_context"] is True


def test_power_bi_dax_uses_canonical_table_and_no_local_metric_formula():
    module = load_module(
        "rga_power_bi_dax_test",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )
    contract = module.load_semantic_contract(
        ROOT / "config" / "rga_semantic_contract.yml",
        "RGA_SYNTHETIC_TESTBED",
    )
    query = contract["verified_queries"][0]
    dax = module.power_bi_dax(contract, query)

    assert "'REINSURANCE_PERFORMANCE'" in dax
    assert "SUMMARIZECOLUMNS" in dax
    for metric in query["metrics"]:
        assert f"[{metric}]" in dax
    assert "NULLIF" not in dax
    assert "SUM(" not in dax
