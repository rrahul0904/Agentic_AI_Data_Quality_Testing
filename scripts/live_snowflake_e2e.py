#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def required(name: str, fallback: str | None = None) -> str:
    value = os.getenv(name) or (os.getenv(fallback) if fallback else None)
    if not value:
        raise SystemExit(f"BLOCKED_EXTERNAL: required environment variable is missing: {name}")
    return value


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
        raise SystemExit(f"unsafe Snowflake identifier: {value!r}")
    return value.upper()


def connection_args() -> dict[str, Any]:
    args: dict[str, Any] = {
        "account": required("SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_ACCOUNT"),
        "user": required("SNOWFLAKE_USER", "ADE_SNOWFLAKE_USER"),
        "warehouse": required("SNOWFLAKE_WAREHOUSE", "ADE_SNOWFLAKE_WAREHOUSE"),
        "database": required("SNOWFLAKE_DATABASE", "ADE_SNOWFLAKE_DATABASE"),
        "schema": required("SNOWFLAKE_SCHEMA", "ADE_SNOWFLAKE_SCHEMA"),
    }
    role = os.getenv("SNOWFLAKE_ROLE") or os.getenv("ADE_SNOWFLAKE_ROLE")
    if role:
        args["role"] = role
    password = os.getenv("SNOWFLAKE_PASSWORD")
    private_key_file = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    if password:
        args["password"] = password
    elif private_key_file:
        args["private_key_file"] = private_key_file
        if os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
            args["private_key_file_pwd"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"]
    else:
        raise SystemExit("BLOCKED_EXTERNAL: configure SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH")
    return args


def main() -> None:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SystemExit("snowflake-connector-python is required for live Snowflake verification") from exc

    args = connection_args()
    table = identifier(os.getenv("ADE_LIVE_SNOWFLAKE_TABLE", "ADE_AGENTIC_RAW_PAYMENT_E2E"))
    stage = identifier(os.getenv("ADE_LIVE_SNOWFLAKE_STAGE", "ADE_AGENTIC_E2E_STAGE"))
    rows = [
        ("p-1001", 100.0, "COMPLETE"),
        ("p-1002", 200.0, "COMPLETE"),
        ("p-1003", 300.0, "SHIPPED"),
    ]

    tmp_path: Path | None = None
    conn = snowflake.connector.connect(**args)
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()")
            identity = cur.fetchone()
            login_query_id = cur.sfqid
            cur.execute(
                f"""CREATE OR REPLACE TEMPORARY TABLE {table} (
                payment_id STRING,
                amount NUMBER(18,2),
                status STRING,
                _batch_id STRING DEFAULT 'agentic-live-e2e',
                _ingested_at TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
                _source_system STRING DEFAULT 'live_csv',
                _row_hash STRING
                )"""
            )
            cur.execute(f"CREATE OR REPLACE TEMPORARY STAGE {stage}")
            handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
            tmp_path = Path(handle.name)
            with handle:
                writer = csv.writer(handle)
                writer.writerow(["payment_id", "amount", "status"])
                writer.writerows(rows)
            cur.execute(f"PUT file://{tmp_path} @{stage} AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
            put_query_id = cur.sfqid
            cur.execute(
                f"""COPY INTO {table} (payment_id, amount, status)
                FROM (SELECT $1, $2::NUMBER(18,2), $3 FROM @{stage})
                FILE_FORMAT=(TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='"')
                ON_ERROR='ABORT_STATEMENT'"""
            )
            copy_result = cur.fetchall()
            copy_query_id = cur.sfqid
            cur.execute(f"UPDATE {table} SET _row_hash=SHA2(payment_id || '|' || amount || '|' || status, 256)")
            cur.execute(f"SELECT COUNT(*), SUM(amount), COUNT_IF(_row_hash IS NULL) FROM {table}")
            count, amount, missing_hash = cur.fetchone()
            reconciliation_query_id = cur.sfqid
            if int(count) != len(rows) or float(amount) != 600.0 or int(missing_hash) != 0:
                raise SystemExit(
                    f"live Snowflake reconciliation failed: count={count}, amount={amount}, missing_hash={missing_hash}"
                )
            print(json.dumps({
                "status": "PASS",
                "mode": "LIVE_SNOWFLAKE",
                "identity": list(identity),
                "login_query_id": login_query_id,
                "put_query_id": put_query_id,
                "copy_query_id": copy_query_id,
                "reconciliation_query_id": reconciliation_query_id,
                "copy_result": copy_result,
                "source_count": len(rows),
                "raw_count": int(count),
                "source_amount": 600.0,
                "raw_amount": float(amount),
                "raw_load": "PASS",
                "reconciliation": "PASS",
            }, indent=2, default=str, sort_keys=True))
        finally:
            cur.close()
    finally:
        conn.close()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    main()
