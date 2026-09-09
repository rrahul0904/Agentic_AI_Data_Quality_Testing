#!/usr/bin/env python3
"""Run the existing ADE read-only Snowflake pipeline RCA against the testbed."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, evidence_path, snowflake_env_missing, testbed_database, update_state, write_json

sys.path.insert(0, str(ROOT / "src"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live"), default="live")
    parser.add_argument("--entity", choices=("reservations",), default="reservations")
    parser.add_argument("--generation-id", help="Limit staged-file inspection to one generated batch")
    parser.add_argument("--stage-pattern", help="Explicit testbed stage regex, used by approved failure certification")
    parser.add_argument("--expected-loaded-rows", type=int)
    parser.add_argument("--json-output", type=Path, default=evidence_path("ade-certification.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = snowflake_env_missing()
    if missing:
        result = {"status": BLOCKED_EXTERNAL, "certification_mode": "NOT_EXECUTED", "error": f"Missing {', '.join(missing)}"}
    else:
        try:
            from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args
            from agentic_data_platform.snowflake import SnowflakePipelineTester

            database = testbed_database()
            connector = connector_from_args({"platform": "snowflake"})
            tester = SnowflakePipelineTester(connector)
            pipe = f"{database}.RAW.PIPE_RESERVATIONS" if args.mode == "live" else None
            result = tester.pipeline_rca(
                stage_name=f"{database}.RAW." + ("STAGE_HOSPITALITY_S3" if args.mode == "live" else "STAGE_HOSPITALITY_INTERNAL"),
                stage_pattern=args.stage_pattern
                or (
                    f".*reservations/generation_id={args.generation_id}/.*[.]csv([.]gz)?$"
                    if args.generation_id
                    else ".*reservations.*[.]csv([.]gz)?$"
                ),
                expected_extensions=[".csv"],
                file_format_name=f"{database}.RAW.FF_HOSPITALITY_CSV_HEADER",
                pipe_name=pipe,
                stream_name=f"{database}.RAW.STREAM_RESERVATIONS",
                max_stream_backlog_rows=int(os.getenv("ADE_LIVE_SNOWFLAKE_MAX_STREAM_BACKLOG_ROWS", "100000")),
                target_table=f"{database}.RAW.RESERVATIONS",
                schema_ignore_target_columns=["_LOAD_ID", "_GENERATION_ID", "_SOURCE_FILE", "_SOURCE_ROW_NUMBER", "_INGESTED_AT"],
                key_columns=["RESERVATION_ID", "_GENERATION_ID"],
                not_null_columns=["RESERVATION_ID", "HOTEL_ID", "GUEST_ID", "CHECKIN_DATE", "CHECKOUT_DATE"],
                freshness_column="_INGESTED_AT",
                max_age_minutes=float(os.getenv("ADE_LIVE_SNOWFLAKE_MAX_AGE_MINUTES", "1560")),
                max_latency_minutes=float(os.getenv("ADE_LIVE_SNOWFLAKE_MAX_LATENCY_MINUTES", "15")),
                expected_loaded_rows=args.expected_loaded_rows,
                max_rejected_rows=0,
                history_hours=24,
            )
            result["certification_mode"] = "LIVE_READ_ONLY_ADE" if args.mode == "live" else "MANUAL_SNOWFLAKE_READ_ONLY_ADE"
            result["ade_status"] = result.get("status", FAIL)
            result["status"] = PASS if result["ade_status"] == PASS else FAIL
        except ExternalConnectionUnavailable as exc:
            result = {"status": BLOCKED_EXTERNAL, "certification_mode": "NOT_EXECUTED", "error": str(exc)}
        except Exception as exc:
            result = {"status": FAIL, "certification_mode": "ATTEMPTED", "error": str(exc)}
    write_json(args.json_output, result)
    update_state(certification_result=result["status"], certification_mode=result.get("certification_mode"))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
