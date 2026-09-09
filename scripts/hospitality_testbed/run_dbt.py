#!/usr/bin/env python3
"""Build and test the hospitality dbt layers and capture invocation evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, evidence_path, snowflake_env_missing, testbed_database, update_state, utc_now, write_json

PROJECT_DIR = ROOT / "hospitality-snowflake-data-platform" / "dbt" / "testbed"
PROFILES_DIR = PROJECT_DIR / "ci_profiles"
SELECTORS = {
    "all": ["tag:testbed_staging", "tag:testbed_core", "tag:testbed_marts"],
    "staging": ["tag:testbed_staging"],
    "core": ["tag:testbed_core"],
    "marts": ["tag:testbed_marts"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=tuple(SELECTORS), default="all")
    parser.add_argument("--json-output", type=Path, default=evidence_path("dbt-results.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = snowflake_env_missing()
    if missing:
        result = {
            "status": BLOCKED_EXTERNAL,
            "testbed_only": True,
            "layer": args.layer,
            "invocation": "NOT_EXECUTED",
            "error": f"Missing {', '.join(missing)}",
        }
    else:
        started_at = utc_now()
        try:
            testbed_database(mutation=True)
            command = [
                sys.executable,
                "-m",
                "dbt.cli.main",
                "build",
                "--project-dir",
                str(PROJECT_DIR),
                "--profiles-dir",
                str(PROFILES_DIR),
                "--select",
                *SELECTORS[args.layer],
            ]
            process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            result = {
                "status": PASS if process.returncode == 0 else FAIL,
                "testbed_only": True,
                "layer": args.layer,
                "started_at": started_at,
                "completed_at": utc_now(),
                "exit_code": process.returncode,
                "stdout_tail": process.stdout[-12000:],
                "stderr_tail": process.stderr[-4000:],
            }
        except Exception as exc:
            result = {
                "status": FAIL,
                "testbed_only": True,
                "layer": args.layer,
                "started_at": started_at,
                "completed_at": utc_now(),
                "error": str(exc),
            }
    write_json(args.json_output, result)
    update_state(dbt_invocation=result["status"], dbt_layer=args.layer)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
