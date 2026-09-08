from __future__ import annotations

from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.finops import (
    expensive_queries,
    full_finops_report,
    query_errors,
    query_history,
    query_patterns,
    warehouse_advisor,
)


class SnowflakeFinOpsFixture:
    def __call__(self, sql: str):
        lowered = sql.casefold()
        if "account_usage.query_history" in lowered:
            return {
                "columns": (
                    "query_id", "query_text", "database_name", "schema_name", "query_type",
                    "warehouse_name", "warehouse_size", "user_name", "role_name", "execution_status",
                    "error_code", "error_message", "total_elapsed_time", "execution_time",
                    "queued_overload_time", "queued_provisioning_time", "bytes_scanned",
                    "bytes_spilled_to_local_storage", "bytes_spilled_to_remote_storage",
                    "rows_produced", "start_time", "end_time",
                ),
                "rows": (
                    {
                        "query_id": "q1",
                        "query_text": "SELECT * FROM FACT_ORDERS WHERE ID = 1",
                        "database_name": "HOTEL",
                        "schema_name": "MART",
                        "query_type": "SELECT",
                        "warehouse_name": "WH_BUSY",
                        "warehouse_size": "SMALL",
                        "user_name": "ANALYST",
                        "role_name": "ANALYST",
                        "execution_status": "SUCCESS",
                        "error_code": None,
                        "error_message": None,
                        "total_elapsed_time": 120000,
                        "execution_time": 110000,
                        "queued_overload_time": 10000,
                        "queued_provisioning_time": 0,
                        "bytes_scanned": 10 * 1024**3,
                        "bytes_spilled_to_local_storage": 1024**3,
                        "bytes_spilled_to_remote_storage": 0,
                        "rows_produced": 1,
                        "start_time": "2026-09-06",
                        "end_time": "2026-09-06",
                    },
                    {
                        "query_id": "q2",
                        "query_text": "SELECT * FROM FACT_ORDERS WHERE ID = 2",
                        "database_name": "HOTEL",
                        "schema_name": "MART",
                        "query_type": "SELECT",
                        "warehouse_name": "WH_BUSY",
                        "warehouse_size": "SMALL",
                        "user_name": "ANALYST",
                        "role_name": "ANALYST",
                        "execution_status": "FAILED",
                        "error_code": "100",
                        "error_message": "timeout",
                        "total_elapsed_time": 30000,
                        "execution_time": 20000,
                        "queued_overload_time": 10000,
                        "queued_provisioning_time": 0,
                        "bytes_scanned": 1024**3,
                        "bytes_spilled_to_local_storage": 0,
                        "bytes_spilled_to_remote_storage": 0,
                        "rows_produced": 0,
                        "start_time": "2026-09-06",
                        "end_time": "2026-09-06",
                    },
                ),
            }
        if "warehouse_metering_history" in lowered:
            return {
                "columns": (
                    "warehouse_name", "credits_used", "compute_credits", "cloud_services_credits",
                    "first_seen", "last_seen",
                ),
                "rows": (
                    {"warehouse_name": "WH_BUSY", "credits_used": 20.0, "compute_credits": 19.0, "cloud_services_credits": 1.0, "first_seen": "a", "last_seen": "b"},
                    {"warehouse_name": "WH_IDLE", "credits_used": 0.0, "compute_credits": 0.0, "cloud_services_credits": 0.0, "first_seen": "a", "last_seen": "b"},
                ),
            }
        if "warehouse_load_history" in lowered:
            return {
                "columns": (
                    "warehouse_name", "avg_running", "peak_running", "avg_queued_load",
                    "peak_queued_load", "avg_queued_provisioning",
                ),
                "rows": (
                    {"warehouse_name": "WH_BUSY", "avg_running": 4.0, "peak_running": 12.0, "avg_queued_load": 1.2, "peak_queued_load": 3.0, "avg_queued_provisioning": 0.1},
                    {"warehouse_name": "WH_IDLE", "avg_running": 0.0, "peak_running": 0.0, "avg_queued_load": 0.0, "peak_queued_load": 0.0, "avg_queued_provisioning": 0.0},
                ),
            }
        if lowered.startswith("show warehouses"):
            return {
                "columns": ("name", "state", "size"),
                "rows": (
                    {"name": "WH_BUSY", "state": "STARTED", "size": "SMALL"},
                    {"name": "WH_IDLE", "state": "SUSPENDED", "size": "XSMALL"},
                ),
            }
        return {"columns": (), "rows": ()}


def connector():
    return SnowflakeConnector(
        SnowflakeFinOpsFixture(),
        SnowflakeConfig(account="a", user="u", database="HOTEL", schema="MART"),
    )


def test_finops_normalizes_history_and_detects_expensive_errors_patterns():
    result = query_history(connector(), days=7)
    assert result["status"] == "PASS"
    assert result["count"] == 2
    history = result["queries"]
    assert expensive_queries(history)[0]["query_id"] == "q1"
    assert query_errors(history)[0]["query_id"] == "q2"
    patterns = query_patterns(history)
    assert patterns[0]["count"] == 2


def test_warehouse_advisor_uses_load_and_metering_evidence():
    result = warehouse_advisor(connector(), days=7)
    by_name = {item["warehouse"]: item for item in result["recommendations"]}
    assert by_name["WH_BUSY"]["action"] == "SCALE_UP"
    assert by_name["WH_BUSY"]["evidence"]["peak_queued_load"] == 3.0
    assert by_name["WH_IDLE"]["action"] == "SUSPEND"


def test_full_finops_report_includes_credits_and_advisor():
    report = full_finops_report(connector(), days=7, credit_price_usd=3.0)
    assert report["status"] == "PASS"
    assert report["cost_summary"]["credits_used"] == 20.0
    assert report["cost_summary"]["estimated_cost_usd"] == 60.0
    assert report["warehouse_advisor"]["recommendations"]
