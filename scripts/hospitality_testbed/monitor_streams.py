#!/usr/bin/env python3
"""Inspect stream metadata and backlog without consuming any stream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, evidence_path, load_yaml, snowflake_connect, testbed_database, write_json

STREAMS = ("STREAM_RESERVATIONS", "STREAM_PAYMENTS", "STREAM_STAYS", "STREAM_CANCELLATIONS", "STREAM_FOLIO_CHARGES")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-backlog", type=int)
    parser.add_argument("--json-output", type=Path, default=evidence_path("stream-health.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    maximum = args.max_backlog if args.max_backlog is not None else int(load_yaml("hospitality_testbed.yml")["service_levels"]["stream_backlog_rows"])
    try:
        database = testbed_database()
        connection = snowflake_connect()
        streams = []
        with connection:
            cursor = connection.cursor()
            cursor.execute(f"SHOW STREAMS IN SCHEMA {database}.RAW")
            columns = [item[0].lower() for item in cursor.description or []]
            inventory = {row[columns.index("name")]: dict(zip(columns, row)) for row in cursor.fetchall()}
            for name in STREAMS:
                qualified = f"{database}.RAW.{name}"
                cursor.execute("SELECT SYSTEM$STREAM_HAS_DATA(%s)", (qualified,))
                has_data = bool(cursor.fetchone()[0])
                cursor.execute(f"SELECT COUNT(*) FROM {qualified}")
                backlog = int(cursor.fetchone()[0])
                streams.append({"stream": qualified, "has_data": has_data, "backlog_rows": backlog, "within_threshold": backlog <= maximum, "metadata": inventory.get(name, {})})
            cursor.close()
        result = {"status": PASS if all(item["within_threshold"] for item in streams) else FAIL, "consumed": False, "max_backlog_rows": maximum, "streams": streams}
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "consumed": False, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "consumed": False, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
