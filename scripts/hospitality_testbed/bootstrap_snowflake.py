#!/usr/bin/env python3
"""Create the isolated hospitality Snowflake testbed from version-controlled DDL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, env, evidence_path, render_sql, snowflake_connect, split_sql, testbed_database, update_state, utc_now, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live"), default="local")
    parser.add_argument("--dry-run", action="store_true", help="Render and validate SQL without connecting")
    parser.add_argument("--json-output", type=Path, default=evidence_path("snowflake-bootstrap.json"))
    return parser.parse_args()


def ddl_files(mode: str) -> list[Path]:
    root = ROOT / "snowflake" / "testbed"
    common = [root / name for name in (
        "00_database.sql", "01_schemas.sql", "02_file_formats.sql", "03_stages.sql", "04_raw_tables.sql",
        "05_streams.sql", "06_cdc_tables.sql", "07_tasks.sql", "08_quality_tables.sql", "09_monitoring_views.sql",
        "10_roles_grants.sql",
    )]
    if mode == "live":
        common.insert(4, root / "03_stages_live.sql")
        common.extend(sorted((root / "pipes").glob("*.sql")))
        common.append(root / "10_roles_grants_live.sql")
    return common


def main() -> int:
    args = parse_args()
    try:
        database = testbed_database(mutation=True)
        rendered = [(path, render_sql(path.read_text(encoding="utf-8"))) for path in ddl_files(args.mode)]
        result = {"status": PASS, "testbed_only": True, "database": database, "mode": args.mode, "dry_run": args.dry_run, "files": [str(path.relative_to(ROOT)) for path, _ in rendered], "statement_count": sum(len(split_sql(sql)) for _, sql in rendered), "started_at": utc_now()}
        if args.dry_run:
            result["completed_at"] = utc_now()
        else:
            connection = snowflake_connect(
                include_database=False,
                include_warehouse=False,
                role=env("ADE_TESTBED_BOOTSTRAP_ROLE", "ACCOUNTADMIN" if args.mode == "live" else "SYSADMIN"),
            )
            with connection:
                cursor = connection.cursor()
                for path, sql in rendered:
                    for statement in split_sql(sql):
                        cursor.execute(statement)
                cursor.close()
            result["completed_at"] = utc_now()
            update_state(snowflake_objects=result["files"], snowflake_bootstrap=PASS, mode=args.mode)
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "mode": args.mode, "dry_run": args.dry_run, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "testbed_only": True, "mode": args.mode, "dry_run": args.dry_run, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
