from agentic_data_platform.platform.airflow_ops import FAILURE_FIXTURES, failure_lab, root_cause_from_error


def test_airflow_failure_lab_covers_master_failure_matrix():
    expected = {
        "bad_connection", "missing_connection", "bad_credentials", "permission_denied",
        "warehouse_unavailable", "dbt_compile_failure", "dbt_test_failure", "schema_drift",
        "missing_source_table", "late_source_data", "duplicate_data", "watermark_regression",
        "timeout", "retry_storm", "stuck_sensor", "pool_starvation", "queue_starvation",
        "dynamic_map_explosion", "xcom_oversize", "dag_import_failure", "deprecated_airflow_api",
        "asset_event_missing", "triggerer_unavailable", "bundle_version_mismatch",
        "snowflake_permission_error",
    }
    assert set(FAILURE_FIXTURES) == expected
    report = failure_lab()
    assert report["fixture_count"] == len(expected)
    assert report["all_fixture_diagnoses_match"] is True
    assert all(item["status"] == "PASS" for item in report["fixtures"])


def test_each_failure_fixture_has_supported_root_cause_and_response():
    for name, fixture in FAILURE_FIXTURES.items():
        result = root_cause_from_error(fixture["error"], dag_id=name, task_id="diagnose")
        assert result["status"] == "DIAGNOSED", name
        assert result["cause"] == fixture["expected"], name
        assert result["confidence"] >= 0.8
        assert result["evidence"] == [fixture["error"]]
        assert result["recommended_action"]


def test_failure_lab_preserves_ui_compatible_default_event():
    report = failure_lab("snowflake_permission_error")
    assert report["event"]["state"] == "FAILED"
    assert report["diagnosis"]["cause"] == "WAREHOUSE_PERMISSION"
