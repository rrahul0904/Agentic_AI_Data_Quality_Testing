#!/usr/bin/env python3
"""Execute a generated RGA SQL artifact against Snowflake with an explicit confirmation gate."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true", help="Required before any Snowflake SQL is executed")
    parser.add_argument("--dry-run", action="store_true", help="Validate request and print SQL metadata without connecting")
    return parser.parse_args()


def validate_request(sql_file: Path, confirm: bool) -> list[str]:
    errors: list[str] = []
    if not sql_file.exists() or not sql_file.is_file():
        errors.append(f"SQL file not found: {sql_file}")
    elif sql_file.suffix.lower() != ".sql":
        errors.append("Only .sql artifacts can be executed")
    if not confirm:
        errors.append("Refusing Snowflake execution without --confirm")
    return errors


def connection_kwargs(env: dict[str, str]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError("Missing Snowflake environment variables: " + ", ".join(missing))
    kwargs: dict[str, Any] = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "warehouse": env["SNOWFLAKE_WAREHOUSE"],
        "role": env.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        "database": env.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED"),
        "session_parameters": {"QUERY_TAG": "RGA_SYNTHETIC_PIPELINE"},
    }
    authenticator = env.get("SNOWFLAKE_AUTHENTICATOR")
    if authenticator:
        kwargs["authenticator"] = authenticator
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    return kwargs


def execute(sql_file: Path, env: dict[str, str]) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live execution") from exc

    connection = snowflake.connector.connect(**connection_kwargs(env))
    statements: list[dict[str, Any]] = []
    try:
        with sql_file.open("r", encoding="utf-8") as handle:
            for cursor in connection.execute_stream(handle, remove_comments=True):
                statements.append(
                    {
                        "query_id": getattr(cursor, "sfqid", None),
                        "rowcount": getattr(cursor, "rowcount", None),
                    }
                )
    finally:
        connection.close()
    return {"status": "PASS", "sql_file": str(sql_file), "statements": statements}


def main() -> int:
    args = parse_args()
    errors = validate_request(args.sql_file, args.confirm)
    if errors:
        print(json.dumps({"status": "REFUSED", "errors": errors}, indent=2))
        return 2
    sql_text = args.sql_file.read_text(encoding="utf-8")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "sql_file": str(args.sql_file),
                    "bytes": len(sql_text.encode("utf-8")),
                    "sha256": __import__("hashlib").sha256(sql_text.encode()).hexdigest(),
                },
                indent=2,
            )
        )
        return 0
    try:
        result = execute(args.sql_file, dict(os.environ))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "sql_file": str(args.sql_file)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
