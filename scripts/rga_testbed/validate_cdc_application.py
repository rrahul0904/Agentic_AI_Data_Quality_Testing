#!/usr/bin/env python3
"""Validate applied synthetic CDC events against Snowflake RAW tables and audit ledger."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Every CDC JSONL row must be an object")
                events.append(value)
    if not events:
        raise ValueError("CDC event file is empty")
    return events


def connection_kwargs(env: dict[str, str], database: str) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError("Missing Snowflake environment variables: " + ", ".join(missing))
    if not (
        env.get("SNOWFLAKE_PASSWORD")
        or env.get("SNOWFLAKE_TOKEN")
        or env.get("SNOWFLAKE_AUTHENTICATOR")
    ):
        raise ValueError("Snowflake authentication is required")
    kwargs: dict[str, Any] = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "warehouse": env["SNOWFLAKE_WAREHOUSE"],
        "role": env.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        "database": database,
        "session_parameters": {"QUERY_TAG": "RGA_CDC_VALIDATE"},
    }
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    return kwargs


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def audit_record_errors(audit: dict[str, Any] | None) -> list[str]:
    errors: list[str] = []
    if not audit:
        return ["audit record is missing"]
    if int(audit.get("count", 0)) != 1:
        errors.append(
            f"audit row count expected 1, got {int(audit.get('count', 0))}"
        )
    statuses = set(audit.get("statuses") or set())
    if statuses != {"APPLIED"}:
        errors.append(
            f"audit status expected only APPLIED, got {sorted(statuses)!r}"
        )
    return errors


def event_check(event: dict[str, Any]) -> dict[str, Any]:
    scenario = event.get("scenario")
    after = event.get("after") or {}
    if scenario == "policy_status_change":
        return {
            "table": "RAW.POLICIES",
            "key_column": "POLICY_ID",
            "key_value": after["policy_id"],
            "fields": {"POLICY_STATUS": after["policy_status"]},
        }
    if scenario == "premium_correction":
        return {
            "table": "RAW.PREMIUMS",
            "key_column": "PREMIUM_TXN_ID",
            "key_value": after["premium_txn_id"],
            "fields": {
                "GROSS_PREMIUM": after["gross_premium"],
                "CEDED_PREMIUM": after["ceded_premium"],
            },
        }
    if scenario == "late_arriving_claim":
        return {
            "table": "RAW.CLAIMS",
            "key_column": "CLAIM_ID",
            "key_value": after["claim_id"],
            "fields": {
                "EVENT_DATE": after["event_date"],
                "REPORTED_DATE": after["reported_date"],
                "CLAIM_STATUS": after["claim_status"],
                "CLAIM_AMOUNT": after["claim_amount"],
                "CEDED_CLAIM_AMOUNT": after["ceded_claim_amount"],
            },
        }
    raise ValueError(f"Unsupported CDC scenario: {scenario}")


def dry_run_payload(events: list[dict[str, Any]], database: str) -> dict[str, Any]:
    scenarios: dict[str, int] = {}
    for event in events:
        event_check(event)
        scenario = str(event["scenario"])
        scenarios[scenario] = scenarios.get(scenario, 0) + 1
    return {
        "status": "DRY_RUN",
        "database": database,
        "event_count": len(events),
        "scenario_counts": scenarios,
        "acceptance": [
            "every event_id exists once in AUDIT.CDC_EVENT_APPLICATIONS with STATUS=APPLIED",
            "policy status corrections match the CDC after image",
            "premium gross/ceded corrections match the CDC after image",
            "late-arriving claims exist with matching dates/status/amounts",
        ],
    }


def validate(events: list[dict[str, Any]], database: str, env: dict[str, str]) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live CDC validation") from exc

    event_ids = [str(event["event_id"]) for event in events]
    placeholders = ", ".join(["%s"] * len(event_ids))
    connection = snowflake.connector.connect(**connection_kwargs(env, database))
    results: list[dict[str, Any]] = []
    audit_rows: dict[str, dict[str, Any]] = {}
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
select EVENT_ID, STATUS, COUNT(*) AS ROW_COUNT
from AUDIT.CDC_EVENT_APPLICATIONS
where EVENT_ID in ({placeholders})
group by EVENT_ID, STATUS
""",
                tuple(event_ids),
            )
            for row in cursor.fetchall():
                event_id = str(row[0])
                status = str(row[1])
                count = int(row[2])
                if event_id in audit_rows:
                    audit_rows[event_id]["count"] += count
                    audit_rows[event_id]["statuses"].add(status)
                else:
                    audit_rows[event_id] = {
                        "count": count,
                        "statuses": {status},
                    }

            for event in events:
                event_id = str(event["event_id"])
                check = event_check(event)
                errors: list[str] = []
                errors.extend(audit_record_errors(audit_rows.get(event_id)))

                columns = list(check["fields"])
                cursor.execute(
                    f"SELECT {', '.join(columns)} FROM {check['table']} "
                    f"WHERE {check['key_column']} = %s",
                    (check["key_value"],),
                )
                rows = cursor.fetchall()
                if len(rows) != 1:
                    errors.append(
                        f"expected exactly one {check['table']} row for {check['key_value']!r}, got {len(rows)}"
                    )
                else:
                    actual = {
                        column: _norm(value)
                        for column, value in zip(columns, rows[0])
                    }
                    for column, expected in check["fields"].items():
                        if actual.get(column) != _norm(expected):
                            errors.append(
                                f"{column} mismatch: expected {_norm(expected)!r}, got {actual.get(column)!r}"
                            )

                results.append(
                    {
                        "event_id": event_id,
                        "scenario": event.get("scenario"),
                        "status": "PASS" if not errors else "FAIL",
                        "errors": errors,
                    }
                )
        finally:
            cursor.close()
    finally:
        connection.close()

    duplicate_ids = len(event_ids) != len(set(event_ids))
    missing_audit = sorted(set(event_ids) - set(audit_rows))
    failed = sum(item["status"] != "PASS" for item in results)
    status = (
        "PASS"
        if not duplicate_ids
        and not missing_audit
        and failed == 0
        and len(audit_rows) == len(event_ids)
        else "FAIL"
    )
    return {
        "status": status,
        "database": database,
        "event_count": len(events),
        "audit_event_count": len(audit_rows),
        "missing_audit_event_ids": missing_audit,
        "duplicate_input_event_ids": duplicate_ids,
        "passed": len(results) - failed,
        "failed": failed,
        "results": results,
    }


def main() -> int:
    args = parse_args()
    try:
        events = load_events(args.events)
        if args.dry_run:
            print(json.dumps(dry_run_payload(events, args.database), indent=2))
            return 0
        if not args.confirm:
            print(json.dumps({"status": "REFUSED", "error": "Refusing live CDC validation without --confirm"}, indent=2))
            return 2
        report = validate(events, args.database, dict(os.environ))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
