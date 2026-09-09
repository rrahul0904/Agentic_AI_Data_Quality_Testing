#!/usr/bin/env python3
"""Read-only live certification for an existing Snowflake ingestion pipeline."""

from __future__ import annotations

import json
import os

from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args
from agentic_data_platform.snowflake import SnowflakePipelineTester


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"BLOCKED_EXTERNAL: required environment variable is missing: {name}")
    return value


def csv_values(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value not in {None, ""} else None


def optional_int(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value not in {None, ""} else None


def optional_json(name: str) -> dict[str, object] | None:
    value = os.getenv(name)
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise SystemExit(f"BLOCKED_EXTERNAL: {name} must contain a JSON object")
    return parsed


def main() -> None:
    stage_name = required("ADE_LIVE_SNOWFLAKE_STAGE")
    file_format_name = required("ADE_LIVE_SNOWFLAKE_FILE_FORMAT")
    pipe_name = required("ADE_LIVE_SNOWFLAKE_PIPE")
    stream_name = required("ADE_LIVE_SNOWFLAKE_STREAM")
    target_table = required("ADE_LIVE_SNOWFLAKE_TARGET_TABLE")

    try:
        connector = connector_from_args({"platform": "snowflake"})
    except ExternalConnectionUnavailable as exc:
        raise SystemExit(f"BLOCKED_EXTERNAL: {exc}") from exc

    tester = SnowflakePipelineTester(connector)
    result = tester.pipeline_rca(
        stage_name=stage_name,
        stage_pattern=os.getenv("ADE_LIVE_SNOWFLAKE_STAGE_PATTERN") or None,
        expected_extensions=csv_values("ADE_LIVE_SNOWFLAKE_EXPECTED_EXTENSIONS"),
        max_stage_file_age_minutes=optional_float("ADE_LIVE_SNOWFLAKE_MAX_STAGE_FILE_AGE_MINUTES"),
        file_format_name=file_format_name,
        file_format_expected=optional_json("ADE_LIVE_SNOWFLAKE_FILE_FORMAT_EXPECTED_JSON"),
        pipe_name=pipe_name,
        stream_name=stream_name,
        max_stream_backlog_rows=optional_int("ADE_LIVE_SNOWFLAKE_MAX_STREAM_BACKLOG_ROWS"),
        target_table=target_table,
        schema_ignore_target_columns=csv_values("ADE_LIVE_SNOWFLAKE_SCHEMA_IGNORE_TARGET_COLUMNS"),
        key_columns=csv_values("ADE_LIVE_SNOWFLAKE_KEY_COLUMNS"),
        not_null_columns=csv_values("ADE_LIVE_SNOWFLAKE_NOT_NULL_COLUMNS"),
        freshness_column=os.getenv("ADE_LIVE_SNOWFLAKE_FRESHNESS_COLUMN") or None,
        max_age_minutes=optional_float("ADE_LIVE_SNOWFLAKE_MAX_AGE_MINUTES"),
        max_latency_minutes=float(os.getenv("ADE_LIVE_SNOWFLAKE_MAX_LATENCY_MINUTES", "15")),
        expected_loaded_rows=optional_int("ADE_LIVE_SNOWFLAKE_EXPECT_LOADED_ROWS"),
        max_rejected_rows=int(os.getenv("ADE_LIVE_SNOWFLAKE_MAX_REJECTED_ROWS", "0")),
        history_hours=int(os.getenv("ADE_LIVE_SNOWFLAKE_HISTORY_HOURS", "24")),
    )
    result["certification_mode"] = "LIVE_SNOWFLAKE_PIPELINE_READ_ONLY"
    print(json.dumps(result, indent=2, default=str, sort_keys=True))
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
