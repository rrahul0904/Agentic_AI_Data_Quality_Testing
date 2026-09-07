#!/usr/bin/env python3
import json
import os
import sys
import time


def emit(payload, code=0):
    print(json.dumps(payload, default=str))
    raise SystemExit(code)


def connect():
    try:
        import snowflake.connector
    except Exception as exc:
        emit({
            "available": False,
            "ok": False,
            "summary": "snowflake-connector-python is not installed.",
            "error": str(exc),
            "installHint": "Run scripts/bootstrap-data-stack.sh or install snowflake-connector-python==4.7.3"
        }, 0)

    name = os.getenv("SNOWFLAKE_CONNECTION_NAME")
    if name:
        return snowflake.connector.connect(connection_name=name)

    keys = {
        "account": os.getenv("SNOWFLAKE_ACCOUNT"),
        "user": os.getenv("SNOWFLAKE_USER"),
        "password": os.getenv("SNOWFLAKE_PASSWORD"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
        "database": os.getenv("SNOWFLAKE_DATABASE"),
        "schema": os.getenv("SNOWFLAKE_SCHEMA"),
        "role": os.getenv("SNOWFLAKE_ROLE"),
        "authenticator": os.getenv("SNOWFLAKE_AUTHENTICATOR"),
    }
    kwargs = {k: v for k, v in keys.items() if v}
    kwargs["session_parameters"] = {"QUERY_TAG": "local-data-harness"}
    if not kwargs.get("account") or not kwargs.get("user"):
        emit({"available": True, "ok": False, "summary": "Snowflake credentials are not configured. Set SNOWFLAKE_CONNECTION_NAME or SNOWFLAKE_ACCOUNT/SNOWFLAKE_USER plus your authentication settings."}, 0)
    return snowflake.connector.connect(**kwargs)


def main():
    operation = sys.argv[1] if len(sys.argv) > 1 else "ping"
    payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    started = time.time()
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                if operation == "ping":
                    cur.execute("select current_version(), current_account(), current_user(), current_role(), current_warehouse(), current_database(), current_schema()")
                    row = cur.fetchone()
                    emit({
                        "available": True,
                        "ok": True,
                        "summary": "Snowflake connection succeeded.",
                        "latencyMs": round((time.time() - started) * 1000),
                        "context": {
                            "version": row[0], "account": row[1], "user": row[2], "role": row[3],
                            "warehouse": row[4], "database": row[5], "schema": row[6]
                        }
                    })
                if operation == "query":
                    sql = payload.get("sql", "")
                    max_rows = max(1, min(500, int(payload.get("maxRows", 100))))
                    cur.execute(sql)
                    columns = [d[0] for d in (cur.description or [])]
                    rows = cur.fetchmany(max_rows)
                    emit({
                        "available": True,
                        "ok": True,
                        "summary": f"Snowflake query returned {len(rows)} row(s).",
                        "latencyMs": round((time.time() - started) * 1000),
                        "columns": columns,
                        "rows": rows,
                        "maxRows": max_rows,
                        "queryId": getattr(cur, "sfqid", None)
                    })
                emit({"available": True, "ok": False, "summary": f"Unknown operation: {operation}"}, 0)
    except Exception as exc:
        emit({"available": True, "ok": False, "summary": "Snowflake operation failed.", "error": str(exc), "errorType": type(exc).__name__}, 0)


if __name__ == "__main__":
    main()
