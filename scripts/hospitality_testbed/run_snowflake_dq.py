#!/usr/bin/env python3
"""Run generation-bounded, read-only DQ queries against Snowflake RAW, CORE, and MARTS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, evidence_path, load_yaml, snowflake_connect, testbed_database, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "hospitality" / "manifest.json")
    parser.add_argument("--layer", choices=("raw", "transformed", "all"), default="all")
    parser.add_argument("--json-output", type=Path, default=evidence_path("snowflake-quality.json"))
    return parser.parse_args()


def rule_queries(database: str, generation_id: str, load_id: str, freshness_hours: int) -> list[dict[str, Any]]:
    bounded = (generation_id, load_id)
    return [
        {"name": "reservation_business_key_not_null", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s AND RESERVATION_ID IS NULL", "params": bounded},
        {"name": "reservation_key_unique_per_generation", "layer": "RAW", "sql": f"SELECT COALESCE(SUM(CNT-1),0) FROM (SELECT RESERVATION_ID, COUNT(*) CNT FROM {database}.RAW.RESERVATIONS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s GROUP BY RESERVATION_ID HAVING COUNT(*)>1)", "params": bounded},
        {"name": "reservation_dates_valid", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s AND CHECKOUT_DATE<CHECKIN_DATE", "params": bounded},
        {"name": "reservation_amount_non_negative", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s AND TOTAL_AMOUNT<0", "params": bounded},
        {"name": "reservation_hotel_exists", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS L LEFT JOIN {database}.RAW.HOTELS R ON L.HOTEL_ID=R.HOTEL_ID AND L._GENERATION_ID=R._GENERATION_ID AND L._LOAD_ID=R._LOAD_ID WHERE L._GENERATION_ID=%s AND L._LOAD_ID=%s AND R.HOTEL_ID IS NULL", "params": bounded},
        {"name": "reservation_guest_exists", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS L LEFT JOIN {database}.RAW.GUESTS R ON L.GUEST_ID=R.GUEST_ID AND L._GENERATION_ID=R._GENERATION_ID AND L._LOAD_ID=R._LOAD_ID WHERE L._GENERATION_ID=%s AND L._LOAD_ID=%s AND R.GUEST_ID IS NULL", "params": bounded},
        {"name": "reservation_room_exists", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS L LEFT JOIN {database}.RAW.ROOMS R ON L.ROOM_ID=R.ROOM_ID AND L._GENERATION_ID=R._GENERATION_ID AND L._LOAD_ID=R._LOAD_ID WHERE L._GENERATION_ID=%s AND L._LOAD_ID=%s AND R.ROOM_ID IS NULL", "params": bounded},
        {"name": "room_belongs_to_hotel", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.ROOMS L LEFT JOIN {database}.RAW.HOTELS R ON L.HOTEL_ID=R.HOTEL_ID AND L._GENERATION_ID=R._GENERATION_ID AND L._LOAD_ID=R._LOAD_ID WHERE L._GENERATION_ID=%s AND L._LOAD_ID=%s AND R.HOTEL_ID IS NULL", "params": bounded},
        {"name": "payment_amount_non_negative", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.PAYMENTS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s AND AMOUNT<0", "params": bounded},
        {"name": "payment_reservation_exists", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.PAYMENTS L LEFT JOIN {database}.RAW.RESERVATIONS R ON L.RESERVATION_ID=R.RESERVATION_ID AND L._GENERATION_ID=R._GENERATION_ID AND L._LOAD_ID=R._LOAD_ID WHERE L._GENERATION_ID=%s AND L._LOAD_ID=%s AND R.RESERVATION_ID IS NULL", "params": bounded},
        {"name": "refund_not_greater_than_payment", "layer": "RAW", "sql": f"SELECT COUNT(*) FROM {database}.RAW.REFUNDS F LEFT JOIN {database}.RAW.PAYMENTS P ON F.PAYMENT_ID=P.PAYMENT_ID AND F._GENERATION_ID=P._GENERATION_ID AND F._LOAD_ID=P._LOAD_ID WHERE F._GENERATION_ID=%s AND F._LOAD_ID=%s AND (P.PAYMENT_ID IS NULL OR F.AMOUNT>P.AMOUNT)", "params": bounded},
        {"name": "raw_freshness", "layer": "RAW", "severity": "WARN", "sql": f"SELECT IFF(MAX(_INGESTED_AT) IS NULL OR DATEDIFF('hour', MAX(_INGESTED_AT), CURRENT_TIMESTAMP())>%s,1,0) FROM {database}.RAW.RESERVATIONS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s", "params": (freshness_hours, *bounded)},
        {"name": "occupied_not_above_available", "layer": "MART", "sql": f"SELECT COUNT(*) FROM {database}.MARTS.MART_DAILY_OCCUPANCY WHERE _GENERATION_ID=%s AND OCCUPIED_ROOMS>AVAILABLE_ROOMS", "params": (generation_id,)},
        {"name": "occupancy_pct_range", "layer": "MART", "sql": f"SELECT COUNT(*) FROM {database}.MARTS.MART_DAILY_OCCUPANCY WHERE _GENERATION_ID=%s AND OCCUPANCY_PCT NOT BETWEEN 0 AND 100", "params": (generation_id,)},
        {"name": "adr_non_negative", "layer": "MART", "sql": f"SELECT COUNT(*) FROM {database}.MARTS.MART_DAILY_REVENUE WHERE _GENERATION_ID=%s AND ADR<0", "params": (generation_id,)},
        {"name": "revpar_non_negative", "layer": "MART", "sql": f"SELECT COUNT(*) FROM {database}.MARTS.MART_DAILY_REVENUE WHERE _GENERATION_ID=%s AND REVPAR<0", "params": (generation_id,)},
        {"name": "refunds_within_gross_payments", "layer": "MART", "sql": f"SELECT COUNT(*) FROM {database}.MARTS.MART_PAYMENT_RECONCILIATION WHERE _GENERATION_ID=%s AND REFUND_AMOUNT>GROSS_PAYMENT_AMOUNT", "params": (generation_id,)},
        {"name": "row_conservation", "layer": "TRANSFORMATION", "sql": f"SELECT ABS((SELECT COUNT(*) FROM {database}.RAW.RESERVATIONS WHERE _GENERATION_ID=%s AND _LOAD_ID=%s)-(SELECT COUNT(*) FROM {database}.CORE.FACT_RESERVATION WHERE _GENERATION_ID=%s))", "params": (generation_id, load_id, generation_id)},
    ]


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        database = testbed_database()
        configured = load_yaml("hospitality_quality.yml")["rules"]
        queries = rule_queries(
            database,
            manifest["generation_id"],
            manifest["load_id"],
            int(load_yaml("hospitality_testbed.yml")["service_levels"]["source_freshness_hours"]),
        )
        configured_names = {item["name"] for item in configured}
        query_names = {item["name"] for item in queries}
        if configured_names != query_names:
            raise ValueError(f"DQ config/query mismatch: missing={sorted(configured_names-query_names)}, extra={sorted(query_names-configured_names)}")
        if args.layer == "raw":
            queries = [item for item in queries if item["layer"] == "RAW"]
        elif args.layer == "transformed":
            queries = [item for item in queries if item["layer"] != "RAW"]
        connection = snowflake_connect()
        checks = []
        with connection:
            cursor = connection.cursor()
            for item in queries:
                cursor.execute(item["sql"], item["params"])
                failed_rows = int(cursor.fetchone()[0] or 0)
                checks.append(
                    {
                        "rule": item["name"],
                        "layer": item["layer"],
                        "severity": item.get("severity", "ERROR"),
                        "status": PASS if failed_rows == 0 else FAIL,
                        "failed_rows": failed_rows,
                    }
                )
            cursor.close()
        result = {
            "status": PASS if all(item["status"] == PASS for item in checks) else FAIL,
            "scope": "READ_ONLY_SNOWFLAKE_GENERATION",
            "testbed_only": True,
            "persisted": False,
            "selected_layer": args.layer,
            "generation_id": manifest["generation_id"],
            "load_id": manifest["load_id"],
            "executed_rule_count": len(checks),
            "checks": checks,
        }
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "scope": "READ_ONLY_SNOWFLAKE_GENERATION", "persisted": False, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "scope": "READ_ONLY_SNOWFLAKE_GENERATION", "persisted": False, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
