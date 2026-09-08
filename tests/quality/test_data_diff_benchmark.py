from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "benchmarks" / "data_diff" / "run.py"
SPEC = importlib.util.spec_from_file_location("data_diff_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_default_scale_suite_covers_contract_sizes():
    assert MODULE.DEFAULT_SIZES == (10_000, 100_000, 1_000_000, 10_000_000)


def test_local_benchmark_finds_change_without_raw_row_transfer():
    result = MODULE.run_case(10_000, max_partition_rows=2_500)
    assert result["result_accuracy"] is True
    assert result["warehouse_pushdown"] is True
    assert result["raw_rows_transferred"] == 0
    assert result["rows_transferred"] < 10_000 * 2
    assert result["queries"] > 0
    assert result["partitions"] > 0


def test_report_never_claims_unexecuted_100m_pass():
    report = MODULE.run_suite((10_000,))
    assert report["status"] == "PASS"
    assert report["claims"]["100m_plus"].startswith("NOT_RUN_LOCAL")
