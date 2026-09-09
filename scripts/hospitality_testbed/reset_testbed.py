#!/usr/bin/env python3
"""Truncate only known testbed data tables after explicit mutation approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_APPROVAL, BLOCKED_EXTERNAL, FAIL, PASS, approved, evidence_path, load_yaml, snowflake_connect, testbed_database, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-database", required=True)
    parser.add_argument("--json-output", type=Path, default=evidence_path("reset.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        database = testbed_database(destructive=True)
        if not approved() or args.confirm_database.upper() != database:
            result = {"status": BLOCKED_APPROVAL, "testbed_only": True, "database": database}
        else:
            raw = [spec["target"].split(".", 1)[1] for spec in load_yaml("hospitality_ingestion.yml")["entities"].values()]
            cdc = ["RESERVATION_CHANGES", "PAYMENT_CHANGES", "STAY_CHANGES", "CANCELLATION_CHANGES", "FOLIO_CHARGE_CHANGES"]
            quality = ["DQ_RESULTS", "RECONCILIATION_RESULTS", "RCA_RESULTS"]
            ops = ["LOAD_RUNS", "FILE_LOAD_RESULTS"]
            staging = [f"STG_{name}" for name in raw]
            core = ["DIM_HOTEL", "DIM_ROOM", "DIM_GUEST", "DIM_DATE", "DIM_BOOKING_CHANNEL", "DIM_LOYALTY_MEMBER", "FACT_RESERVATION", "FACT_STAY", "FACT_PAYMENT", "FACT_FOLIO_CHARGE", "FACT_INVENTORY_DAILY", "FACT_ROOM_RATE"]
            marts = ["MART_DAILY_OCCUPANCY", "MART_DAILY_REVENUE", "MART_BOOKING_CHANNEL_PERFORMANCE", "MART_CANCELLATION_ANALYSIS", "MART_GUEST_LIFETIME_VALUE", "MART_PROPERTY_PERFORMANCE", "MART_PAYMENT_RECONCILIATION", "MART_RESERVATION_FUNNEL"]
            stream_tables = {
                "STREAM_RESERVATIONS": "RESERVATIONS",
                "STREAM_PAYMENTS": "PAYMENTS",
                "STREAM_STAYS": "STAYS",
                "STREAM_CANCELLATIONS": "CANCELLATIONS",
                "STREAM_FOLIO_CHARGES": "FOLIO_CHARGES",
            }
            statements = [
                *(f"TRUNCATE TABLE {database}.RAW.{name}" for name in raw),
                *(f"TRUNCATE TABLE {database}.CDC.{name}" for name in cdc),
                *(f"TRUNCATE TABLE {database}.QUALITY.{name}" for name in quality),
                *(f"TRUNCATE TABLE {database}.OPS.{name}" for name in ops),
                *(f"DROP VIEW IF EXISTS {database}.STAGING.{name}" for name in staging),
                *(f"DROP TABLE IF EXISTS {database}.CORE.{name}" for name in core),
                *(f"DROP TABLE IF EXISTS {database}.MARTS.{name}" for name in marts),
                *(
                    f"CREATE OR REPLACE STREAM {database}.RAW.{stream} ON TABLE {database}.RAW.{table} APPEND_ONLY=FALSE"
                    for stream, table in stream_tables.items()
                ),
            ]
            connection = snowflake_connect()
            with connection:
                cursor = connection.cursor()
                for statement in statements:
                    cursor.execute(statement)
                cursor.close()
            result = {"status": PASS, "testbed_only": True, "database": database, "reset_statements": len(statements), "streams_rebased": len(stream_tables)}
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "error": str(exc)}
    except ValueError as exc:
        result = {"status": BLOCKED_APPROVAL, "testbed_only": True, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "testbed_only": True, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
