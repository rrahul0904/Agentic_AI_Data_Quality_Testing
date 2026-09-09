from __future__ import annotations

from agentic_data_platform.snowflake import failure_lab


def test_failure_lab_lists_repeatable_negative_scenarios():
    result = failure_lab()
    assert result["status"] == "PASS"
    assert result["mutation_executed"] is False
    assert result["scenario_count"] == 8
    assert {
        "malformed_csv",
        "bad_number",
        "invalid_timestamp",
        "missing_required_column",
        "extra_source_column",
        "null_required",
        "duplicate_key",
        "zero_byte_file",
    } == set(result["available_scenarios"])
    assert all(item["mutation_executed"] is False for item in result["scenarios"])


def test_failure_lab_can_select_one_scenario():
    result = failure_lab(scenario="invalid_timestamp", prefix="qa")
    assert result["status"] == "PASS"
    assert result["scenario_count"] == 1
    scenario = result["scenarios"][0]
    assert scenario["fixture_path"] == "qa/reservation_bad_timestamp.csv"
    assert scenario["expected_first_divergence"] == "SNOWPIPE_LOAD"


def test_failure_lab_rejects_unknown_scenario():
    result = failure_lab(scenario="does-not-exist")
    assert result["status"] == "FAIL"
    assert result["mutation_executed"] is False
    assert "invalid_timestamp" in result["available_scenarios"]
