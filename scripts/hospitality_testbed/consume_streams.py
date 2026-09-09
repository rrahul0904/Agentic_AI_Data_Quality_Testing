#!/usr/bin/env python3
"""Explicitly consume testbed streams into CDC audit tables after approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_APPROVAL, BLOCKED_EXTERNAL, FAIL, PASS, approved, evidence_path, snowflake_connect, testbed_database, write_json

MAPPINGS = {
    "reservations": ("STREAM_RESERVATIONS", "CDC.RESERVATION_CHANGES", "RESERVATION_ID", "OBJECT_CONSTRUCT_KEEP_NULL('hotel_id', HOTEL_ID, 'guest_id', GUEST_ID, 'room_id', ROOM_ID, 'status', BOOKING_STATUS)"),
    "payments": ("STREAM_PAYMENTS", "CDC.PAYMENT_CHANGES", "PAYMENT_ID", "OBJECT_CONSTRUCT_KEEP_NULL('reservation_id', RESERVATION_ID, 'status', PAYMENT_STATUS, 'amount', AMOUNT)"),
    "stays": ("STREAM_STAYS", "CDC.STAY_CHANGES", "STAY_ID", "OBJECT_CONSTRUCT_KEEP_NULL('reservation_id', RESERVATION_ID, 'hotel_id', HOTEL_ID, 'room_id', ROOM_ID, 'status', STAY_STATUS)"),
    "cancellations": ("STREAM_CANCELLATIONS", "CDC.CANCELLATION_CHANGES", "CANCELLATION_ID", "OBJECT_CONSTRUCT_KEEP_NULL('reservation_id', RESERVATION_ID, 'reason', REASON, 'fee_amount', FEE_AMOUNT)"),
    "folio_charges": ("STREAM_FOLIO_CHARGES", "CDC.FOLIO_CHARGE_CHANGES", "FOLIO_ID", "OBJECT_CONSTRUCT_KEEP_NULL('reservation_id', RESERVATION_ID, 'charge_type', CHARGE_TYPE, 'amount', AMOUNT)"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Required in addition to ADE_TESTBED_MUTATION_APPROVED=true")
    parser.add_argument("--entity", choices=tuple(MAPPINGS), action="append")
    parser.add_argument("--json-output", type=Path, default=evidence_path("cdc-processing.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute or not approved():
        result = {"status": BLOCKED_APPROVAL, "testbed_only": True, "mutates": ["streams", "cdc_tables"], "message": "Pass --execute and set ADE_TESTBED_MUTATION_APPROVED=true"}
    else:
        try:
            database = testbed_database(mutation=True)
            connection = snowflake_connect()
            counts = {}
            with connection:
                cursor = connection.cursor()
                for entity in args.entity or list(MAPPINGS):
                    stream, target, key, payload = MAPPINGS[entity]
                    sql = f"INSERT INTO {database}.{target} ({key}, ACTION, IS_UPDATE, GENERATION_ID, LOAD_ID, PAYLOAD) SELECT {key}, METADATA$ACTION, METADATA$ISUPDATE, _GENERATION_ID, _LOAD_ID, {payload} FROM {database}.RAW.{stream}"
                    cursor.execute(sql)
                    counts[entity] = cursor.rowcount
                cursor.close()
            result = {"status": PASS, "testbed_only": True, "consumed": True, "rows_by_entity": counts}
        except RuntimeError as exc:
            result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "error": str(exc)}
        except Exception as exc:
            result = {"status": FAIL, "testbed_only": True, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
