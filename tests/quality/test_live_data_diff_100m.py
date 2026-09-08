from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "live_data_diff_100m.py"


def _module():
    spec = importlib.util.spec_from_file_location("live_data_diff_100m", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_100m_validation_requires_expected_counts_and_zero_raw_egress():
    module = _module()
    result = {
        "status": "FAIL",
        "changed_keys": [[5]],
        "missing_keys": [],
        "extra_keys": [],
        "raw_rows_retrieved": 0,
        "warehouse_pushdown": True,
    }
    matched, detail = module._validate_result(
        result,
        {"status": "FAIL", "changed": 1, "missing": 0, "extra": 0},
    )
    assert matched is True
    assert detail["expected_match"] is True
    assert detail["zero_raw_rows_transferred"] is True


def test_100m_validation_fails_when_raw_rows_move_or_expected_diff_mismatches():
    module = _module()
    result = {
        "status": "FAIL",
        "changed_keys": [[5], [6]],
        "missing_keys": [],
        "extra_keys": [],
        "raw_rows_retrieved": 2,
        "warehouse_pushdown": True,
    }
    matched, detail = module._validate_result(
        result,
        {"status": "FAIL", "changed": 1, "missing": 0, "extra": 0},
    )
    assert matched is False
    assert detail["expected_match"] is False
    assert detail["zero_raw_rows_transferred"] is False


def test_100m_expectation_config_is_explicit(monkeypatch):
    module = _module()
    for name in (
        "ADE_DATA_DIFF_EXPECT_STATUS",
        "ADE_DATA_DIFF_EXPECT_CHANGED_KEYS",
        "ADE_DATA_DIFF_EXPECT_MISSING_KEYS",
        "ADE_DATA_DIFF_EXPECT_EXTRA_KEYS",
    ):
        monkeypatch.delenv(name, raising=False)
    assert module._expected_diff() is None

    monkeypatch.setenv("ADE_DATA_DIFF_EXPECT_STATUS", "FAIL")
    monkeypatch.setenv("ADE_DATA_DIFF_EXPECT_CHANGED_KEYS", "1")
    monkeypatch.setenv("ADE_DATA_DIFF_EXPECT_MISSING_KEYS", "2")
    monkeypatch.setenv("ADE_DATA_DIFF_EXPECT_EXTRA_KEYS", "3")
    assert module._expected_diff() == {
        "status": "FAIL",
        "changed": 1,
        "missing": 2,
        "extra": 3,
    }
