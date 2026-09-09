#!/usr/bin/env python3
"""Execute manifest-bounded COPY commands in local/manual Snowflake mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, evidence_path, snowflake_connect, testbed_database, update_state, write_json
from render_copy_commands import copy_commands


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live"), default="local")
    parser.add_argument("--exclude-snowpipe", action="store_true", help="Load only non-pipe reference feeds in live mode")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "hospitality" / "manifest.json")
    parser.add_argument("--json-output", type=Path, default=evidence_path("copy-results.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        testbed_database(mutation=True)
        commands = copy_commands(manifest, args.mode, exclude_snowpipe=args.exclude_snowpipe)
        results = []
        connection = snowflake_connect()
        with connection:
            cursor = connection.cursor()
            for item in commands:
                cursor.execute(item["sql"])
                columns = [column[0].lower() for column in cursor.description or []]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()] if columns else []
                results.append(
                    {
                        "entity": item["entity"],
                        "file": item["file"],
                        "stage_file": item["stage_file"],
                        "expected_rows": item["expected_rows"],
                        "copy_output": rows,
                    }
                )
            cursor.close()
        rejected = sum(int(row.get("errors_seen") or 0) for item in results for row in item["copy_output"])
        failed_files = []
        for item in results:
            output = item["copy_output"]
            loaded_rows = sum(int(row.get("rows_loaded") or 0) for row in output)
            statuses = {str(row.get("status") or "").upper() for row in output}
            if not output or statuses != {"LOADED"} or loaded_rows != item["expected_rows"]:
                failed_files.append(
                    {
                        "file": item["file"],
                        "expected_rows": item["expected_rows"],
                        "loaded_rows": loaded_rows,
                        "statuses": sorted(statuses),
                    }
                )
        result = {
            "status": PASS if rejected == 0 and not failed_files else FAIL,
            "testbed_only": True,
            "generation_id": manifest["generation_id"],
            "load_id": manifest["load_id"],
            "commands_executed": len(results),
            "rejected_rows": rejected,
            "failed_files": failed_files,
            "results": results,
        }
        update_state(files_loaded=len(results), load_id=manifest["load_id"])
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "testbed_only": True, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
