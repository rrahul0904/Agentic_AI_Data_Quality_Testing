from __future__ import annotations

import json

from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.snowflake import SnowflakePipelineTester, analyze_copy_command


class SnowflakePipelineFixture:
    def __call__(self, sql: str):
        lowered = sql.casefold()
        if lowered.startswith("show pipes"):
            return {"columns": ("name", "database_name", "schema_name", "definition", "owner"), "rows": (
                {"name": "RES_PIPE", "database_name": "HOTEL", "schema_name": "RAW", "definition": "COPY INTO RAW.RESERVATION FROM @LANDING", "owner": "SYSADMIN"},
            )}
        if "system$pipe_status" in lowered:
            return {"columns": ("PIPE_STATUS",), "rows": ({"PIPE_STATUS": json.dumps({"executionState": "RUNNING", "pendingFileCount": 0})},)}
        if lowered.startswith("show streams like"):
            return {"columns": ("name", "stale", "stale_after", "table_name", "mode"), "rows": (
                {"name": "RES_STREAM", "stale": "false", "stale_after": "2026-09-10", "table_name": "RESERVATION", "mode": "DEFAULT"},
            )}
        if lowered.startswith("show streams"):
            return {"columns": ("name", "database_name", "schema_name", "table_name", "stale"), "rows": (
                {"name": "RES_STREAM", "database_name": "HOTEL", "schema_name": "RAW", "table_name": "RESERVATION", "stale": "false"},
            )}
        if "system$stream_has_data" in lowered:
            return {"columns": ("HAS_DATA",), "rows": ({"HAS_DATA": True},)}
        if "copy_history" in lowered:
            return {"columns": ("FILE_NAME", "STATUS", "ROW_COUNT", "ERROR_COUNT"), "rows": (
                {"FILE_NAME": "reservation_001.csv", "STATUS": "LOADED", "ROW_COUNT": 100, "ERROR_COUNT": 0},
            )}
        if "table(validate" in lowered:
            return {"columns": ("ERROR",), "rows": ()}
        if "duplicate_rows" in lowered:
            return {"columns": ("DUPLICATE_ROWS",), "rows": ({"DUPLICATE_ROWS": 0},)}
        if lowered.startswith("select count(*)"):
            return {"columns": ("ROW_COUNT", "NULL_COUNT_0", "FRESHNESS_LAG_MINUTES"), "rows": (
                {"ROW_COUNT": 100, "NULL_COUNT_0": 0, "FRESHNESS_LAG_MINUTES": 4},
            )}
        raise AssertionError(f"unexpected SQL: {sql}")


def tester() -> SnowflakePipelineTester:
    connector = SnowflakeConnector(
        SnowflakePipelineFixture(),
        SnowflakeConfig(database="HOTEL", schema="RAW"),
    )
    return SnowflakePipelineTester(connector)


def test_copy_command_analysis_flags_high_risk_options():
    result = analyze_copy_command(
        "COPY INTO RAW.RESERVATION FROM @LANDING FILE_FORMAT=(TYPE=CSV) ON_ERROR='CONTINUE' FORCE=TRUE"
    )
    assert result["status"] == "WARN"
    assert result["target"] == "RAW.RESERVATION"
    assert result["source"] == "@LANDING"
    assert result["options"]["force"] is True
    assert {item["code"] for item in result["findings"]} >= {"FORCE_ENABLED"}


def test_copy_command_analysis_rejects_non_copy_sql():
    assert analyze_copy_command("DELETE FROM RAW.RESERVATION")["status"] == "FAIL"


def test_pipe_and_stream_health_are_read_only_and_structured():
    sf = tester()
    assert sf.pipe_inventory()["pipe_count"] == 1
    assert sf.pipe_status("HOTEL.RAW.RES_PIPE")["status"] == "PASS"
    streams = sf.stream_inventory()
    assert streams["status"] == "PASS"
    stream = sf.stream_status("HOTEL.RAW.RES_STREAM")
    assert stream["has_data"] is True
    assert stream["stale"] is False


def test_copy_history_and_validate_contract():
    sf = tester()
    history = sf.copy_history("HOTEL.RAW.RESERVATION")
    assert history["status"] == "PASS"
    assert history["loaded_row_count"] == 100
    validation = sf.validate_copy("HOTEL.RAW.RESERVATION")
    assert validation["status"] == "PASS"
    assert validation["error_count"] == 0


def test_pipeline_quality_combines_volume_null_unique_and_freshness():
    sf = tester()
    quality = sf.table_quality(
        "HOTEL.RAW.RESERVATION",
        key_columns=["RESERVATION_ID"],
        not_null_columns=["RESERVATION_ID"],
        freshness_column="INGESTED_AT",
        max_age_minutes=15,
    )
    assert quality["status"] == "PASS"
    assert quality["failed_check_count"] == 0
    assert {check["check"] for check in quality["checks"]} == {"minimum_rows", "not_null", "unique_key", "freshness"}


def test_end_to_end_pipeline_health_rolls_up_components():
    sf = tester()
    health = sf.pipeline_health(
        pipe_name="HOTEL.RAW.RES_PIPE",
        stream_name="HOTEL.RAW.RES_STREAM",
        target_table="HOTEL.RAW.RESERVATION",
        key_columns=["RESERVATION_ID"],
        not_null_columns=["RESERVATION_ID"],
        freshness_column="INGESTED_AT",
        max_age_minutes=15,
    )
    assert health["status"] == "PASS"
    assert set(health["components"]) == {"pipe", "stream", "copy_history", "quality"}
