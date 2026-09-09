"""Deterministic Snowflake ingestion failure fixtures.

The failure lab returns safe fixture payloads and expected evidence. It never
uploads files or mutates Snowflake. Staging/execution belongs to an explicitly
approved external test workflow.
"""

from __future__ import annotations

from typing import Any


_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "malformed_csv",
        "filename": "reservation_malformed.csv",
        "content": 'reservation_id,guest_name,arrival_ts,amount\n1001,"Unclosed quote,2026-09-09 10:00:00,145.00\n',
        "expected_first_divergence": "SNOWPIPE_LOAD",
        "expected_error_class": "CSV_PARSE_ERROR",
        "purpose": "Verify malformed delimited records are surfaced as load errors rather than disappearing downstream.",
    },
    {
        "id": "bad_number",
        "filename": "reservation_bad_number.csv",
        "content": "reservation_id,guest_name,arrival_ts,amount\n1002,Alex,2026-09-09 10:05:00,NOT_A_NUMBER\n",
        "expected_first_divergence": "SNOWPIPE_LOAD",
        "expected_error_class": "NUMERIC_CONVERSION",
        "purpose": "Verify datatype conversion failures are visible in COPY/Snowpipe validation evidence.",
    },
    {
        "id": "invalid_timestamp",
        "filename": "reservation_bad_timestamp.csv",
        "content": "reservation_id,guest_name,arrival_ts,amount\n1003,Mina,not-a-timestamp,90.00\n",
        "expected_first_divergence": "SNOWPIPE_LOAD",
        "expected_error_class": "TIMESTAMP_CONVERSION",
        "purpose": "Verify invalid timestamp values are rejected and attributed to the correct file/column.",
    },
    {
        "id": "missing_required_column",
        "filename": "reservation_missing_column.csv",
        "content": "reservation_id,guest_name,amount\n1004,Sam,220.00\n",
        "expected_first_divergence": "SCHEMA_DRIFT",
        "expected_error_class": "MISSING_SOURCE_COLUMN",
        "purpose": "Verify producer schema contraction is detected before downstream publication.",
    },
    {
        "id": "extra_source_column",
        "filename": "reservation_extra_column.csv",
        "content": "reservation_id,guest_name,arrival_ts,amount,unexpected_flag\n1005,Lee,2026-09-09 10:10:00,180.00,Y\n",
        "expected_first_divergence": "SCHEMA_DRIFT",
        "expected_error_class": "SOURCE_COLUMN_NOT_IN_TARGET",
        "purpose": "Verify producer schema expansion is detected explicitly.",
    },
    {
        "id": "null_required",
        "filename": "reservation_null_required.csv",
        "content": "reservation_id,guest_name,arrival_ts,amount\n,Jordan,2026-09-09 10:15:00,130.00\n",
        "expected_first_divergence": "TARGET_DQ",
        "expected_error_class": "NOT_NULL",
        "purpose": "Verify required-key nulls fail target-table DQ even if the load itself succeeds.",
    },
    {
        "id": "duplicate_key",
        "filename": "reservation_duplicate_key.csv",
        "content": (
            "reservation_id,guest_name,arrival_ts,amount\n"
            "1006,Riley,2026-09-09 10:20:00,105.00\n"
            "1006,Riley,2026-09-09 10:20:00,105.00\n"
        ),
        "expected_first_divergence": "TARGET_DQ",
        "expected_error_class": "DUPLICATE_KEY",
        "purpose": "Verify duplicate business keys are detected after ingestion.",
    },
    {
        "id": "zero_byte_file",
        "filename": "reservation_zero_byte.csv",
        "content": "",
        "expected_first_divergence": "STAGE",
        "expected_error_class": "ZERO_BYTE_FILE",
        "purpose": "Verify empty staged files fail before Snowpipe/COPY analysis.",
    },
)


def failure_lab(*, scenario: str | None = None, prefix: str = "ade_failure") -> dict[str, Any]:
    selected = [dict(item) for item in _SCENARIOS if scenario is None or item["id"] == scenario]
    if scenario is not None and not selected:
        return {
            "status": "FAIL",
            "mode": "LOCAL_FIXTURE_PLAN",
            "mutation_executed": False,
            "error": f"Unknown Snowflake failure scenario: {scenario}",
            "available_scenarios": [item["id"] for item in _SCENARIOS],
        }

    for item in selected:
        item["fixture_path"] = f"{prefix}/{item['filename']}"
        item["mutation_required_for_live_run"] = True
        item["mutation_executed"] = False

    return {
        "status": "PASS",
        "mode": "LOCAL_FIXTURE_PLAN",
        "mutation_executed": False,
        "scenario_count": len(selected),
        "available_scenarios": [item["id"] for item in _SCENARIOS],
        "scenarios": selected,
        "live_execution_boundary": (
            "Fixtures are generated locally only. Uploading/staging them and triggering a load "
            "requires an explicitly approved external test workflow."
        ),
    }
