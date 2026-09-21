#!/usr/bin/env python3
"""Collect bounded Snowflake Query History evidence for physical-acceleration analysis."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")
DEFAULT_OUTPUT = Path("artifacts/rga_query_history.json")

_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+((?:[A-Z_][A-Z0-9_$]*\.){0,2}[A-Z_][A-Z0-9_$]*)",
    re.IGNORECASE,
)
_WHERE_RE = re.compile(
    r"\bWHERE\b(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bQUALIFY\b|\bLIMIT\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_PREDICATE_RE = re.compile(
    r"(?:\b[A-Z_][A-Z0-9_$]*\.)?([A-Z_][A-Z0-9_$]*)\s*"
    r"(=|<>|!=|<=|>=|<|>|\bIN\b|\bBETWEEN\b|\bLIKE\b|\bILIKE\b|\bRLIKE\b)",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--query-tag-prefix", default="RGA_SEMANTIC_BENCHMARK")
    parser.add_argument("--database")
    parser.add_argument("--include-query-text", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_request(days: int, limit: int, confirm: bool, dry_run: bool) -> list[str]:
    errors: list[str] = []
    if days < 1 or days > 14:
        errors.append("days must be between 1 and 14 so QAS eligibility estimates remain actionable")
    if limit < 1 or limit > 100000:
        errors.append("limit must be between 1 and 100000")
    if not dry_run and not confirm:
        errors.append("Refusing live Query History collection without --confirm")
    return errors


def connection_kwargs(env: dict[str, str]) -> dict[str, Any]:
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
        "database": env.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED"),
        "session_parameters": {"QUERY_TAG": "RGA_WORKLOAD_HISTORY_COLLECTOR"},
    }
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    return kwargs


def query_shape(sql: str) -> dict[str, Any]:
    tables = sorted({item.upper() for item in _TABLE_RE.findall(sql or "")})
    predicates: list[dict[str, str]] = []
    match = _WHERE_RE.search(sql or "")
    if match:
        seen: set[tuple[str, str]] = set()
        for column, operator in _PREDICATE_RE.findall(match.group(1)):
            key = (column.upper(), operator.upper())
            if key in seen:
                continue
            seen.add(key)
            predicates.append({"column": key[0], "operator": key[1]})
    return {
        "tables": tables,
        "predicates": predicates,
        "has_selective_predicate_shape": any(
            item["operator"] in {"=", "IN", "BETWEEN", "<", "<=", ">", ">="}
            for item in predicates
        ),
    }


def collection_plan(
    *,
    days: int,
    limit: int,
    query_tag_prefix: str,
    database: str | None,
    include_query_text: bool,
) -> dict[str, Any]:
    return {
        "status": "DRY_RUN",
        "source": "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        "days": days,
        "limit": limit,
        "query_tag_prefix": query_tag_prefix,
        "database": database,
        "include_query_text": include_query_text,
        "fields": [
            "query_id",
            "query_hash",
            "query_parameterized_hash",
            "warehouse_name",
            "database_name",
            "schema_name",
            "query_tag",
            "total_elapsed_time",
            "execution_time",
            "compilation_time",
            "queued_overload_time",
            "bytes_scanned",
            "partitions_scanned",
            "partitions_total",
            "percentage_scanned_from_cache",
            "bytes_spilled_to_local_storage",
            "bytes_spilled_to_remote_storage",
            "query_acceleration_bytes_scanned",
            "query_acceleration_partitions_scanned",
            "query_acceleration_upper_limit_scale_factor",
            "query_load_percent",
        ],
        "privacy": (
            "Query text is excluded by default. Structural table/predicate hints are extracted "
            "in memory; use --include-query-text only when retaining SQL text is explicitly acceptable."
        ),
    }


def _history_sql(database_filter: bool) -> str:
    db_clause = "and upper(database_name) = upper(%s)" if database_filter else ""
    return f"""
select
  query_id,
  query_text,
  query_hash,
  query_hash_version,
  query_parameterized_hash,
  query_parameterized_hash_version,
  start_time,
  warehouse_name,
  database_name,
  schema_name,
  query_tag,
  total_elapsed_time,
  execution_time,
  compilation_time,
  queued_overload_time,
  bytes_scanned,
  partitions_scanned,
  partitions_total,
  percentage_scanned_from_cache,
  bytes_spilled_to_local_storage,
  bytes_spilled_to_remote_storage,
  query_acceleration_bytes_scanned,
  query_acceleration_partitions_scanned,
  query_acceleration_upper_limit_scale_factor,
  query_load_percent,
  execution_status
from snowflake.account_usage.query_history
where start_time >= dateadd(day, -%s, current_timestamp())
  and query_tag ilike %s
  {db_clause}
  and execution_status = 'SUCCESS'
order by start_time desc
limit %s
"""


def collect(
    *,
    env: dict[str, str],
    days: int,
    limit: int,
    query_tag_prefix: str,
    database: str | None,
    include_query_text: bool,
) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live Query History collection") from exc

    params: list[Any] = [days, f"{query_tag_prefix}%"]
    if database:
        params.append(database)
    params.append(limit)

    connection = snowflake.connector.connect(**connection_kwargs(env))
    rows: list[dict[str, Any]] = []
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(_history_sql(bool(database)), tuple(params))
            columns = [item[0].lower() for item in cursor.description]
            for raw in cursor.fetchall():
                item = dict(zip(columns, raw))
                query_text = str(item.pop("query_text") or "")
                shape = query_shape(query_text)
                item["sql_sha256"] = hashlib.sha256(query_text.encode()).hexdigest()
                item["shape"] = shape
                if include_query_text:
                    item["query_text"] = query_text
                rows.append(item)
        finally:
            cursor.close()
    finally:
        connection.close()

    return {
        "status": "PASS",
        "source": "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        "days": days,
        "query_tag_prefix": query_tag_prefix,
        "database": database,
        "query_count": len(rows),
        "queries": rows,
        "privacy": {
            "query_text_retained": include_query_text,
            "structural_hints_only_by_default": not include_query_text,
        },
    }


def main() -> int:
    args = parse_args()
    errors = validate_request(args.days, args.limit, args.confirm, args.dry_run)
    if errors:
        print(json.dumps({"status": "REFUSED", "errors": errors}, indent=2))
        return 2

    if args.dry_run:
        print(
            json.dumps(
                collection_plan(
                    days=args.days,
                    limit=args.limit,
                    query_tag_prefix=args.query_tag_prefix,
                    database=args.database,
                    include_query_text=args.include_query_text,
                ),
                indent=2,
            )
        )
        return 0

    try:
        report = collect(
            env=dict(os.environ),
            days=args.days,
            limit=args.limit,
            query_tag_prefix=args.query_tag_prefix,
            database=args.database,
            include_query_text=args.include_query_text,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "query_count": report["query_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
