#!/usr/bin/env python3
"""Capture and validate semantic metric effects of synthetic CDC events."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")
METRIC_COLUMNS = (
    "GROSS_PREMIUM",
    "CEDED_PREMIUM",
    "GROSS_CLAIM_AMOUNT",
    "CEDED_CLAIM_AMOUNT",
    "CLAIM_COUNT",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--mode", choices=("capture", "validate"), required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("Every CDC event must be a JSON object")
                events.append(payload)
    if not events:
        raise ValueError("CDC event file is empty")
    return events


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _grain_key(grain: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(grain["cedant_id"]),
        str(grain["treaty_id"]),
        str(grain["period_month"]),
    )


def build_expectations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregates: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "gross_premium_delta": Decimal("0.00"),
            "ceded_premium_delta": Decimal("0.00"),
            "gross_claim_amount_delta": Decimal("0.00"),
            "ceded_claim_amount_delta": Decimal("0.00"),
            "claim_count_delta": 0,
            "event_ids": [],
            "scenarios": [],
        }
    )

    for event in events:
        scenario = event.get("scenario")
        if scenario == "policy_status_change":
            # Policy status is dimension state. Current exposure rows are not regenerated
            # from status, so no MART metric delta is asserted for this scenario.
            continue

        grain = event.get("semantic_grain")
        if not isinstance(grain, dict):
            raise ValueError(
                f"CDC event {event.get('event_id')} scenario {scenario} is missing semantic_grain"
            )
        key = _grain_key(grain)
        target = aggregates[key]
        target["event_ids"].append(str(event.get("event_id")))
        target["scenarios"].append(str(scenario))

        if scenario == "premium_correction":
            before = event.get("before") or {}
            after = event.get("after") or {}
            target["gross_premium_delta"] += _money(after.get("gross_premium")) - _money(
                before.get("gross_premium")
            )
            target["ceded_premium_delta"] += _money(after.get("ceded_premium")) - _money(
                before.get("ceded_premium")
            )
        elif scenario == "late_arriving_claim":
            after = event.get("after") or {}
            target["gross_claim_amount_delta"] += _money(after.get("claim_amount"))
            target["ceded_claim_amount_delta"] += _money(after.get("ceded_claim_amount"))
            target["claim_count_delta"] += 1
        else:
            raise ValueError(f"Unsupported semantic CDC scenario: {scenario}")

    expectations: list[dict[str, Any]] = []
    for (cedant_id, treaty_id, period_month), values in sorted(aggregates.items()):
        expectations.append(
            {
                "grain": {
                    "cedant_id": cedant_id,
                    "treaty_id": treaty_id,
                    "period_month": period_month,
                },
                "deltas": {
                    "gross_premium": str(values["gross_premium_delta"].quantize(Decimal("0.01"))),
                    "ceded_premium": str(values["ceded_premium_delta"].quantize(Decimal("0.01"))),
                    "gross_claim_amount": str(values["gross_claim_amount_delta"].quantize(Decimal("0.01"))),
                    "ceded_claim_amount": str(values["ceded_claim_amount_delta"].quantize(Decimal("0.01"))),
                    "claim_count": int(values["claim_count_delta"]),
                },
                "event_ids": sorted(values["event_ids"]),
                "scenarios": sorted(set(values["scenarios"])),
            }
        )
    if not expectations:
        raise ValueError("No CDC events have semantic metric effects to validate")
    return expectations


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
        "session_parameters": {"QUERY_TAG": "RGA_CDC_SEMANTIC_EFFECT"},
    }
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    return kwargs


def _row_payload(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {
            "row_exists": False,
            "gross_premium": "0.00",
            "ceded_premium": "0.00",
            "gross_claim_amount": "0.00",
            "ceded_claim_amount": "0.00",
            "claim_count": 0,
        }
    return {
        "row_exists": True,
        "gross_premium": str(_money(row[0])),
        "ceded_premium": str(_money(row[1])),
        "gross_claim_amount": str(_money(row[2])),
        "ceded_claim_amount": str(_money(row[3])),
        "claim_count": int(row[4] or 0),
    }


def query_grain(cursor: Any, database: str, grain: dict[str, str]) -> dict[str, Any]:
    cursor.execute(
        f"""
select
  GROSS_PREMIUM,
  CEDED_PREMIUM,
  GROSS_CLAIM_AMOUNT,
  CEDED_CLAIM_AMOUNT,
  CLAIM_COUNT
from {database}.MART.REINSURANCE_PERFORMANCE
where CEDANT_ID = %s
  and TREATY_ID = %s
  and PERIOD_MONTH = %s::DATE
""",
        (
            grain["cedant_id"],
            grain["treaty_id"],
            grain["period_month"],
        ),
    )
    rows = cursor.fetchall()
    if len(rows) > 1:
        raise ValueError(
            "MART.REINSURANCE_PERFORMANCE returned duplicate rows for grain "
            f"{grain}"
        )
    return _row_payload(rows[0] if rows else None)


def capture(
    expectations: list[dict[str, Any]],
    database: str,
    env: dict[str, str],
) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live semantic CDC validation") from exc

    connection = snowflake.connector.connect(**connection_kwargs(env, database))
    captured: list[dict[str, Any]] = []
    try:
        cursor = connection.cursor()
        try:
            for expectation in expectations:
                captured.append(
                    {
                        **expectation,
                        "baseline": query_grain(
                            cursor,
                            database,
                            expectation["grain"],
                        ),
                    }
                )
        finally:
            cursor.close()
    finally:
        connection.close()

    return {
        "baseline_version": 1,
        "database": database,
        "grain_count": len(captured),
        "expectations": captured,
    }


def expected_post(baseline: dict[str, Any], deltas: dict[str, Any]) -> dict[str, Any]:
    return {
        "gross_premium": str(
            (_money(baseline["gross_premium"]) + _money(deltas["gross_premium"])).quantize(
                Decimal("0.01")
            )
        ),
        "ceded_premium": str(
            (_money(baseline["ceded_premium"]) + _money(deltas["ceded_premium"])).quantize(
                Decimal("0.01")
            )
        ),
        "gross_claim_amount": str(
            (
                _money(baseline["gross_claim_amount"])
                + _money(deltas["gross_claim_amount"])
            ).quantize(Decimal("0.01"))
        ),
        "ceded_claim_amount": str(
            (
                _money(baseline["ceded_claim_amount"])
                + _money(deltas["ceded_claim_amount"])
            ).quantize(Decimal("0.01"))
        ),
        "claim_count": int(baseline["claim_count"]) + int(deltas["claim_count"]),
    }


def validate(
    baseline_report: dict[str, Any],
    database: str,
    env: dict[str, str],
) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live semantic CDC validation") from exc

    if baseline_report.get("database") != database:
        raise ValueError(
            f"Baseline database {baseline_report.get('database')!r} does not match {database!r}"
        )

    connection = snowflake.connector.connect(**connection_kwargs(env, database))
    results: list[dict[str, Any]] = []
    try:
        cursor = connection.cursor()
        try:
            for item in baseline_report.get("expectations", []):
                grain = item["grain"]
                actual = query_grain(cursor, database, grain)
                expected = expected_post(item["baseline"], item["deltas"])
                errors: list[str] = []
                for metric in METRIC_COLUMNS:
                    key = metric.lower()
                    actual_value = actual[key]
                    expected_value = expected[key]
                    if metric == "CLAIM_COUNT":
                        equal = int(actual_value) == int(expected_value)
                    else:
                        equal = _money(actual_value) == _money(expected_value)
                    if not equal:
                        errors.append(
                            f"{metric} expected {expected_value!r}, got {actual_value!r}"
                        )
                if not actual["row_exists"] and any(
                    _money(expected[name]) != Decimal("0.00")
                    for name in (
                        "gross_premium",
                        "ceded_premium",
                        "gross_claim_amount",
                        "ceded_claim_amount",
                    )
                ):
                    errors.append("expected semantic MART row does not exist")
                results.append(
                    {
                        "grain": grain,
                        "status": "PASS" if not errors else "FAIL",
                        "scenarios": item.get("scenarios", []),
                        "event_ids": item.get("event_ids", []),
                        "baseline": item["baseline"],
                        "deltas": item["deltas"],
                        "expected_post": expected,
                        "actual_post": actual,
                        "errors": errors,
                    }
                )
        finally:
            cursor.close()
    finally:
        connection.close()

    failed = sum(item["status"] != "PASS" for item in results)
    return {
        "status": "PASS" if results and failed == 0 else "FAIL",
        "database": database,
        "grain_count": len(results),
        "passed": len(results) - failed,
        "failed": failed,
        "results": results,
        "note": (
            "Policy status changes are validated at RAW/DIM state only. "
            "No exposure delta is asserted because current synthetic exposure rows are not regenerated from policy status."
        ),
    }


def dry_run_payload(events: list[dict[str, Any]], database: str) -> dict[str, Any]:
    expectations = build_expectations(events)
    return {
        "status": "DRY_RUN",
        "database": database,
        "grain_count": len(expectations),
        "expectations": expectations,
        "note": (
            "Premium corrections assert exact gross/ceded premium deltas. "
            "Late claims assert exact gross/ceded claim and claim-count deltas. "
            "Policy lapse has no MART metric delta assertion in the current model."
        ),
    }


def main() -> int:
    args = parse_args()
    try:
        events = load_events(args.events)
        if args.dry_run:
            print(json.dumps(dry_run_payload(events, args.database), indent=2))
            return 0
        if not args.confirm:
            print(
                json.dumps(
                    {
                        "status": "REFUSED",
                        "error": "Refusing live CDC semantic-effect validation without --confirm",
                    },
                    indent=2,
                )
            )
            return 2

        expectations = build_expectations(events)
        if args.mode == "capture":
            report = capture(expectations, args.database, dict(os.environ))
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            args.baseline.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "baseline": str(args.baseline),
                        "grain_count": report["grain_count"],
                    },
                    indent=2,
                )
            )
            return 0

        if not args.baseline.exists():
            raise FileNotFoundError(f"CDC semantic baseline not found: {args.baseline}")
        baseline_report = json.loads(args.baseline.read_text(encoding="utf-8"))
        report = validate(baseline_report, args.database, dict(os.environ))
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
