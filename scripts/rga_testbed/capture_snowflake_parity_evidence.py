#!/usr/bin/env python3
"""Capture governed Snowflake Semantic View evidence for parity certification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--security-context")
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def connection_kwargs(env: dict[str, str]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError("Missing Snowflake environment variables: " + ", ".join(missing))
    if not (
        env.get("SNOWFLAKE_PASSWORD")
        or env.get("SNOWFLAKE_TOKEN")
        or env.get("SNOWFLAKE_AUTHENTICATOR")
    ):
        raise ValueError(
            "Snowflake authentication is required via SNOWFLAKE_PASSWORD, "
            "SNOWFLAKE_TOKEN, or SNOWFLAKE_AUTHENTICATOR"
        )
    kwargs: dict[str, Any] = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "warehouse": env["SNOWFLAKE_WAREHOUSE"],
        "role": env.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        "database": env.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED"),
        "session_parameters": {"QUERY_TAG": "RGA_CONSUMER_EVIDENCE"},
    }
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    return kwargs


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_plan(manifest_path: Path, evidence_dir: Path, max_rows: int) -> dict[str, Any]:
    if max_rows < 1 or max_rows > 100000:
        raise ValueError("max_rows must be between 1 and 100000")
    manifest = load_json(manifest_path)
    cases = []
    for case in manifest.get("cases", []):
        sql_file = manifest_path.parent / case["reference"]["sql_file"]
        cases.append(
            {
                "case_id": case["id"],
                "sql_file": str(sql_file),
                "sql_exists": sql_file.exists(),
                "output": str(evidence_dir / f"{case['id']}.snowflake_semantic_view.json"),
                "expected_columns": case.get("dimensions", []) + case.get("metrics", []),
            }
        )
    return {
        "manifest": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "max_rows": max_rows,
        "case_count": len(cases),
        "cases": cases,
    }


def run(
    manifest_path: Path,
    evidence_dir: Path,
    *,
    security_context: str | None,
    max_rows: int,
    env: dict[str, str],
) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live evidence capture") from exc

    plan = build_plan(manifest_path, evidence_dir, max_rows)
    missing_sql = [item["sql_file"] for item in plan["cases"] if not item["sql_exists"]]
    if missing_sql:
        raise FileNotFoundError("Missing parity reference SQL: " + ", ".join(missing_sql))

    role = security_context or env.get("SNOWFLAKE_ROLE", "SYSADMIN")
    if security_context and env.get("SNOWFLAKE_ROLE") and security_context != env.get("SNOWFLAKE_ROLE"):
        raise ValueError(
            f"security_context {security_context!r} does not match SNOWFLAKE_ROLE {env.get('SNOWFLAKE_ROLE')!r}"
        )

    evidence_dir.mkdir(parents=True, exist_ok=True)
    connection = snowflake.connector.connect(**connection_kwargs(env))
    results: list[dict[str, Any]] = []
    try:
        cursor = connection.cursor()
        try:
            for case in plan["cases"]:
                sql_path = Path(case["sql_file"])
                sql = sql_path.read_text(encoding="utf-8")
                cursor.execute(sql)
                query_id = getattr(cursor, "sfqid", None)
                columns = [str(item[0]).upper() for item in (cursor.description or [])]
                rows = cursor.fetchmany(max_rows + 1)
                if len(rows) > max_rows:
                    results.append(
                        {
                            "case_id": case["case_id"],
                            "status": "FAIL",
                            "error": f"result exceeds max_rows={max_rows}; evidence would be truncated",
                            "query_id": query_id,
                        }
                    )
                    continue
                expected = [str(item).upper() for item in case["expected_columns"]]
                if sorted(columns) != sorted(expected):
                    results.append(
                        {
                            "case_id": case["case_id"],
                            "status": "FAIL",
                            "error": f"column mismatch: expected {expected}, got {columns}",
                            "query_id": query_id,
                        }
                    )
                    continue
                row_payload = [
                    {columns[index]: _normalize(value) for index, value in enumerate(row)}
                    for row in rows
                ]
                output = evidence_dir / f"{case['case_id']}.snowflake_semantic_view.json"
                payload = {
                    "case_id": case["case_id"],
                    "consumer": "snowflake_semantic_view",
                    "security_context": role,
                    "capture_status": "CAPTURED",
                    "capture_method": "snowflake_semantic_view_reference_sql",
                    "query_id": query_id,
                    "source_sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                    "rows": row_payload,
                }
                output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                results.append(
                    {
                        "case_id": case["case_id"],
                        "status": "PASS",
                        "query_id": query_id,
                        "row_count": len(row_payload),
                        "output": str(output),
                    }
                )
        finally:
            cursor.close()
    finally:
        connection.close()

    failed = sum(item["status"] != "PASS" for item in results)
    return {
        "status": "PASS" if results and failed == 0 else "FAIL",
        "consumer": "snowflake_semantic_view",
        "security_context": role,
        "case_count": len(results),
        "passed": len(results) - failed,
        "failed": failed,
        "results": results,
    }


def main() -> int:
    args = parse_args()
    plan = build_plan(args.manifest, args.evidence_dir, args.max_rows)
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN", **plan}, indent=2))
        return 0
    if not args.confirm:
        print(json.dumps({"status": "REFUSED", "error": "Refusing live Snowflake evidence capture without --confirm"}, indent=2))
        return 2
    try:
        report = run(
            args.manifest,
            args.evidence_dir,
            security_context=args.security_context,
            max_rows=args.max_rows,
            env=dict(os.environ),
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
