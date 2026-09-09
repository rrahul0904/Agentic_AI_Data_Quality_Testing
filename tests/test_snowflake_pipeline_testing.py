from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.snowflake import SnowflakePipelineTester, analyze_copy_command


class SnowflakePipelineFixture:
    def __call__(self, sql: str):
        lowered = sql.casefold()
        now = datetime.now(timezone.utc)

        if lowered.startswith("show stages"):
            return {"columns": ("name", "database_name", "schema_name", "type", "url"), "rows": (
                {"name": "LANDING", "database_name": "HOTEL", "schema_name": "RAW", "type": "EXTERNAL", "url": "s3://bucket/hotel/"},
            )}
        if lowered.startswith("list @"):
            return {"columns": ("name", "size", "md5", "last_modified"), "rows": (
                {
                    "name": "s3://bucket/hotel/reservation_001.csv",
                    "size": 2048,
                    "md5": "abc",
                    "last_modified": (now - timedelta(minutes=5)).isoformat(),
                },
            )}
        if lowered.startswith("desc file format"):
            return {"columns": ("property_name", "property_value"), "rows": (
                {"property_name": "TYPE", "property_value": "CSV"},
                {"property_name": "FIELD_DELIMITER", "property_value": ","},
                {"property_name": "SKIP_HEADER", "property_value": "1"},
                {"property_name": "COMPRESSION", "property_value": "AUTO"},
            )}
        if lowered.startswith("show pipes"):
            return {"columns": ("name", "database_name", "schema_name", "definition", "owner"), "rows": (
                {"name": "RES_PIPE", "database_name": "HOTEL", "schema_name": "RAW", "definition": "COPY INTO RAW.RESERVATION FROM @LANDING", "owner": "SYSADMIN"},
            )}
        if "system$pipe_status" in lowered:
            return {"columns": ("PIPE_STATUS",), "rows": (
                {"PIPE_STATUS": json.dumps({"executionState": "RUNNING", "pendingFileCount": 0})},
            )}
        if lowered.startswith("show streams like"):
            return {"columns": ("name", "stale", "stale_after", "table_name", "mode"), "rows": (
                {"name": "RES_STREAM", "stale": "false", "stale_after": (now + timedelta(days=1)).isoformat(), "table_name": "RESERVATION", "mode": "DEFAULT"},
            )}
        if lowered.startswith("show streams"):
            return {"columns": ("name", "database_name", "schema_name", "table_name", "stale"), "rows": (
                {"name": "RES_STREAM", "database_name": "HOTEL", "schema_name": "RAW", "table_name": "RESERVATION", "stale": "false"},
            )}
        if "system$stream_has_data" in lowered:
            return {"columns": ("HAS_DATA",), "rows": ({"HAS_DATA": True},)}
        if "metadata$action" in lowered:
            return {"columns": ("PENDING_ROWS", "INSERT_ROWS", "DELETE_ROWS", "UPDATE_MARKER_ROWS"), "rows": (
                {"PENDING_ROWS": 4, "INSERT_ROWS": 4, "DELETE_ROWS": 0, "UPDATE_MARKER_ROWS": 0},
            )}
        if "copy_history" in lowered:
            return {
                "columns": ("FILE_NAME", "LAST_LOAD_TIME", "STATUS", "ROW_COUNT", "ROW_PARSED", "ERROR_COUNT"),
                "rows": (
                    {
                        "FILE_NAME": "reservation_001.csv",
                        "LAST_LOAD_TIME": (now - timedelta(minutes=2)).isoformat(),
                        "STATUS": "LOADED",
                        "ROW_COUNT": 100,
                        "ROW_PARSED": 100,
                        "ERROR_COUNT": 0,
                    },
                ),
            }
        if "validate_pipe_load" in lowered:
            return {"columns": ("ERROR",), "rows": ()}
        if "table(validate" in lowered:
            return {"columns": ("ERROR",), "rows": ()}
        if "infer_schema" in lowered:
            return {"columns": ("COLUMN_NAME", "TYPE", "NULLABLE", "ORDER_ID"), "rows": (
                {"COLUMN_NAME": "RESERVATION_ID", "TYPE": "NUMBER", "NULLABLE": False, "ORDER_ID": 1},
                {"COLUMN_NAME": "GUEST_NAME", "TYPE": "TEXT", "NULLABLE": True, "ORDER_ID": 2},
            )}
        if lowered.startswith("desc table"):
            return {"columns": ("name", "type", "null?", "default"), "rows": (
                {"name": "RESERVATION_ID", "type": "NUMBER(38,0)", "null?": "N", "default": None},
                {"name": "GUEST_NAME", "type": "VARCHAR", "null?": "Y", "default": None},
                {"name": "INGESTED_AT", "type": "TIMESTAMP_NTZ", "null?": "N", "default": "CURRENT_TIMESTAMP()"},
            )}
        if "duplicate_rows" in lowered:
            return {"columns": ("DUPLICATE_ROWS",), "rows": ({"DUPLICATE_ROWS": 0},)}
        if "target_row_count" in lowered:
            return {"columns": ("TARGET_ROW_COUNT",), "rows": ({"TARGET_ROW_COUNT": 100},)}
        if lowered.startswith("select count(*) as row_count"):
            return {"columns": ("ROW_COUNT", "NULL_COUNT_0", "FRESHNESS_LAG_MINUTES"), "rows": (
                {"ROW_COUNT": 100, "NULL_COUNT_0": 0, "FRESHNESS_LAG_MINUTES": 4},
            )}
        raise AssertionError(f"unexpected SQL: {sql}")


class ZeroByteStageFixture(SnowflakePipelineFixture):
    def __call__(self, sql: str):
        if sql.casefold().startswith("list @"):
            return {"columns": ("name", "size", "md5", "last_modified"), "rows": (
                {
                    "name": "s3://bucket/hotel/bad.csv",
                    "size": 0,
                    "md5": "",
                    "last_modified": datetime.now(timezone.utc).isoformat(),
                },
            )}
        return super().__call__(sql)


def _tester(executor=None) -> SnowflakePipelineTester:
    connector = SnowflakeConnector(
        executor or SnowflakePipelineFixture(),
        SnowflakeConfig(database="HOTEL", schema="RAW"),
    )
    return SnowflakePipelineTester(connector)


def test_copy_command_analysis_flags_partial_load_and_force_risk():
    result = analyze_copy_command(
        "COPY INTO RAW.RESERVATION FROM @LANDING FILE_FORMAT=(TYPE=CSV) ON_ERROR='CONTINUE' FORCE=TRUE"
    )
    assert result["status"] == "WARN"
    assert result["target"] == "RAW.RESERVATION"
    assert result["source"] == "@LANDING"
    assert result["options"]["force"] is True
    assert {item["code"] for item in result["findings"]} >= {"FORCE_ENABLED", "PARTIAL_LOAD_ALLOWED"}


def test_copy_command_analysis_rejects_non_copy_sql():
    assert analyze_copy_command("DELETE FROM RAW.RESERVATION")["status"] == "FAIL"


def test_stage_and_file_format_contracts_are_structured():
    sf = _tester()
    assert sf.stage_inventory()["stage_count"] == 1
    stage = sf.stage_files(
        "HOTEL.RAW.LANDING",
        expected_extensions=[".csv"],
        max_age_minutes=30,
    )
    assert stage["status"] == "PASS"
    assert stage["file_count"] == 1
    assert stage["zero_byte_file_count"] == 0

    file_format = sf.file_format_status(
        "HOTEL.RAW.RES_CSV",
        expected={"TYPE": "CSV", "FIELD_DELIMITER": ",", "SKIP_HEADER": 1},
    )
    assert file_format["status"] == "PASS"


def test_pipe_stream_and_backlog_health_are_read_only_and_structured():
    sf = _tester()
    assert sf.pipe_inventory()["pipe_count"] == 1
    assert sf.pipe_status("HOTEL.RAW.RES_PIPE")["status"] == "PASS"
    assert sf.stream_inventory()["status"] == "PASS"
    stream = sf.stream_status("HOTEL.RAW.RES_STREAM")
    assert stream["has_data"] is True
    assert stream["stale"] is False
    backlog = sf.stream_backlog("HOTEL.RAW.RES_STREAM", max_pending_rows=10)
    assert backlog["status"] == "PASS"
    assert backlog["pending_rows"] == 4


def test_copy_history_validate_and_reconciliation_contract():
    sf = _tester()
    history = sf.copy_history("HOTEL.RAW.RESERVATION")
    assert history["status"] == "PASS"
    assert history["parsed_row_count"] == 100
    assert history["loaded_row_count"] == 100
    assert sf.validate_pipe_load("HOTEL.RAW.RES_PIPE")["error_count"] == 0
    assert sf.validate_copy("HOTEL.RAW.RESERVATION")["error_count"] == 0

    reconciliation = sf.reconcile_load(
        "HOTEL.RAW.RESERVATION",
        expected_loaded_rows=100,
    )
    assert reconciliation["status"] == "PASS"
    assert reconciliation["rejected_rows"] == 0
    assert reconciliation["acceptance_pct"] == 100.0


def test_schema_drift_and_latency_are_verified_against_stage_evidence():
    sf = _tester()
    drift = sf.schema_drift(
        "HOTEL.RAW.LANDING",
        "HOTEL.RAW.RESERVATION",
        "HOTEL.RAW.RES_CSV",
        ignore_target_columns=["INGESTED_AT"],
    )
    assert drift["status"] == "PASS"
    assert drift["source_column_count"] == 2

    latency = sf.ingestion_latency(
        "HOTEL.RAW.LANDING",
        "HOTEL.RAW.RESERVATION",
        pipe_name="HOTEL.RAW.RES_PIPE",
        max_latency_minutes=15,
    )
    assert latency["status"] == "PASS"
    assert latency["matched_file_count"] == 1
    assert latency["stuck_file_count"] == 0
    assert latency["p95_minutes"] is not None
    assert latency["p95_minutes"] <= 15


def test_pipeline_quality_combines_volume_null_unique_and_freshness():
    sf = _tester()
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


def test_end_to_end_pipeline_health_rolls_up_stage_to_target_evidence():
    sf = _tester()
    health = sf.pipeline_health(
        stage_name="HOTEL.RAW.LANDING",
        expected_extensions=["csv"],
        file_format_name="HOTEL.RAW.RES_CSV",
        file_format_expected={"TYPE": "CSV"},
        pipe_name="HOTEL.RAW.RES_PIPE",
        stream_name="HOTEL.RAW.RES_STREAM",
        max_stream_backlog_rows=10,
        target_table="HOTEL.RAW.RESERVATION",
        schema_ignore_target_columns=["INGESTED_AT"],
        key_columns=["RESERVATION_ID"],
        not_null_columns=["RESERVATION_ID"],
        freshness_column="INGESTED_AT",
        max_age_minutes=15,
        max_latency_minutes=15,
        expected_loaded_rows=100,
    )
    assert health["status"] == "PASS"
    assert set(health["components"]) == {
        "stage_files",
        "file_format",
        "pipe",
        "pipe_validation",
        "stream",
        "stream_backlog",
        "copy_history",
        "latency",
        "schema_drift",
        "quality",
        "reconciliation",
    }


def test_deterministic_rca_reports_first_stage_divergence():
    sf = _tester(ZeroByteStageFixture())
    rca = sf.pipeline_rca(
        stage_name="HOTEL.RAW.LANDING",
        expected_extensions=["csv"],
    )
    assert rca["status"] == "FAIL"
    assert rca["first_divergence"] == "STAGE"
    assert rca["first_component"] == "stage_files"
    assert rca["recommended_actions"]
