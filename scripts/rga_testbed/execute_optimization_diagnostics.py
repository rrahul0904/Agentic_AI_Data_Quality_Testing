#!/usr/bin/env python3
"""Execute only approved read-only Snowflake optimization diagnostics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")
ALLOWED_FUNCTIONS = (
    "SYSTEM$ESTIMATE_QUERY_ACCELERATION",
    "SYSTEM$CLUSTERING_INFORMATION",
    "SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def extract_statements(sql_text: str) -> list[str]:
    uncommented = "\n".join(
        line for line in sql_text.splitlines() if not line.lstrip().startswith("--")
    )
    return [
        statement.strip()
        for statement in uncommented.split(";")
        if statement.strip()
    ]


def validate_statements(statements: list[str]) -> list[str]:
    errors: list[str] = []
    for index, statement in enumerate(statements, 1):
        normalized = " ".join(statement.upper().split())
        if not normalized.startswith("SELECT "):
            errors.append(
                f"statement {index} is not SELECT-only: {statement[:80]}"
            )
            continue
        if not any(function in normalized for function in ALLOWED_FUNCTIONS):
            errors.append(
                f"statement {index} does not call an approved optimization diagnostic"
            )
        forbidden = (
            " ALTER ",
            " CREATE ",
            " DROP ",
            " INSERT ",
            " UPDATE ",
            " DELETE ",
            " MERGE ",
            " COPY ",
            " PUT ",
            " REMOVE ",
            " CALL ",
        )
        padded = f" {normalized} "
        if any(token in padded for token in forbidden):
            errors.append(f"statement {index} contains a forbidden mutation token")
    return errors


def validate_request(
    sql_file: Path,
    *,
    confirm: bool,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    statements: list[str] = []
    if not sql_file.exists() or not sql_file.is_file():
        errors.append(f"SQL file not found: {sql_file}")
    elif sql_file.suffix.lower() != ".sql":
        errors.append("Only .sql diagnostic artifacts are accepted")
    else:
        statements = extract_statements(sql_file.read_text(encoding="utf-8"))
        errors.extend(validate_statements(statements))
    if not statements and not errors:
        errors.append("No approved diagnostic statements were found")
    if not dry_run and not confirm:
        errors.append("Refusing live optimization diagnostics without --confirm")
    return errors, statements


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
        "session_parameters": {"QUERY_TAG": "RGA_OPTIMIZATION_DIAGNOSTICS"},
    }
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    return kwargs


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def execute(statements: list[str], env: dict[str, str]) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError(
            "snowflake-connector-python is required for live optimization diagnostics"
        ) from exc

    connection = snowflake.connector.connect(**connection_kwargs(env))
    results: list[dict[str, Any]] = []
    try:
        cursor = connection.cursor()
        try:
            for index, statement in enumerate(statements, 1):
                cursor.execute(statement)
                columns = [str(item[0]).upper() for item in (cursor.description or [])]
                rows = cursor.fetchall()
                results.append(
                    {
                        "statement": index,
                        "query_id": getattr(cursor, "sfqid", None),
                        "columns": columns,
                        "rows": [
                            {
                                columns[position]: _normalize(value)
                                for position, value in enumerate(row)
                            }
                            for row in rows
                        ],
                    }
                )
        finally:
            cursor.close()
    finally:
        connection.close()
    return {
        "status": "PASS",
        "statement_count": len(statements),
        "results": results,
    }


def main() -> int:
    args = parse_args()
    errors, statements = validate_request(
        args.sql_file,
        confirm=args.confirm,
        dry_run=args.dry_run,
    )
    if errors:
        print(json.dumps({"status": "REFUSED", "errors": errors}, indent=2))
        return 2

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "statement_count": len(statements),
                    "allowed_functions": list(ALLOWED_FUNCTIONS),
                },
                indent=2,
            )
        )
        return 0

    try:
        report = execute(statements, dict(os.environ))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report["output"] = str(args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
