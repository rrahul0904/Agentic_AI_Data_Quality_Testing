#!/usr/bin/env python3
"""Drop only explicitly configured hospitality testbed resources after dual approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_APPROVAL, BLOCKED_EXTERNAL, FAIL, PASS, approved, env, evidence_path, snowflake_connect, testbed_database, utc_now, validate_identifier, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-database", required=True, help="Must exactly match ADE_SNOWFLAKE_DATABASE")
    parser.add_argument("--include-account-objects", action="store_true", help="Also drop testbed warehouse, role and storage integration")
    parser.add_argument("--json-output", type=Path, default=evidence_path("snowflake-teardown.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        database = testbed_database(destructive=True)
    except Exception as exc:
        result = {"status": BLOCKED_APPROVAL, "testbed_only": True, "error": str(exc)}
    else:
        if not approved() or args.confirm_database.upper() != database:
            result = {"status": BLOCKED_APPROVAL, "testbed_only": True, "database": database, "message": "Set ADE_TESTBED_MUTATION_APPROVED=true and pass the exact database to --confirm-database"}
        else:
            try:
                statements = [f"DROP DATABASE IF EXISTS {database}"]
                if args.include_account_objects:
                    warehouse = validate_identifier(env("ADE_SNOWFLAKE_WAREHOUSE", "ADE_HOSPITALITY_TESTBED_WH") or "", "warehouse")
                    role = validate_identifier(env("ADE_SNOWFLAKE_ROLE", "ADE_HOSPITALITY_TESTBED_ROLE") or "", "role")
                    integration = validate_identifier(env("ADE_TESTBED_STORAGE_INTEGRATION", "ADE_HOSPITALITY_S3_INT") or "", "integration")
                    if not all("HOSPITALITY" in value for value in (warehouse, role, integration)):
                        raise ValueError("Account-level teardown targets must contain HOSPITALITY")
                    statements.extend((f"DROP WAREHOUSE IF EXISTS {warehouse}", f"DROP INTEGRATION IF EXISTS {integration}", f"DROP ROLE IF EXISTS {role}"))
                connection = snowflake_connect(include_database=False)
                with connection:
                    cursor = connection.cursor()
                    for statement in statements:
                        cursor.execute(statement)
                    cursor.close()
                result = {"status": PASS, "testbed_only": True, "database": database, "dropped_objects": statements, "completed_at": utc_now()}
            except RuntimeError as exc:
                result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "error": str(exc)}
            except Exception as exc:
                result = {"status": FAIL, "testbed_only": True, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
