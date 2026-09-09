#!/usr/bin/env python3
"""Read-only live certification for existing Snowflake ingestion objects."""

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


def main() -> None:
    pipe_name = required("ADE_LIVE_SNOWFLAKE_PIPE")
    stream_name = required("ADE_LIVE_SNOWFLAKE_STREAM")
    target_table = required("ADE_LIVE_SNOWFLAKE_TARGET_TABLE")
    key_columns = [item.strip() for item in os.getenv("ADE_LIVE_SNOWFLAKE_KEY_COLUMNS", "").split(",") if item.strip()]
    not_null_columns = [item.strip() for item in os.getenv("ADE_LIVE_SNOWFLAKE_NOT_NULL_COLUMNS", "").split(",") if item.strip()]
    freshness_column = os.getenv("ADE_LIVE_SNOWFLAKE_FRESHNESS_COLUMN") or None
    max_age_raw = os.getenv("ADE_LIVE_SNOWFLAKE_MAX_AGE_MINUTES")
    max_age_minutes = float(max_age_raw) if max_age_raw else None

    try:
        connector = connector_from_args({"platform": "snowflake"})
    except ExternalConnectionUnavailable as exc:
        raise SystemExit(f"BLOCKED_EXTERNAL: {exc}") from exc

    tester = SnowflakePipelineTester(connector)
    result = tester.pipeline_health(
        pipe_name=pipe_name,
        stream_name=stream_name,
        target_table=target_table,
        key_columns=key_columns,
        not_null_columns=not_null_columns,
        freshness_column=freshness_column,
        max_age_minutes=max_age_minutes,
        history_hours=int(os.getenv("ADE_LIVE_SNOWFLAKE_HISTORY_HOURS", "24")),
    )
    result["mode"] = "LIVE_SNOWFLAKE_PIPELINE_READ_ONLY"
    print(json.dumps(result, indent=2, default=str, sort_keys=True))
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
