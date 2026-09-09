#!/usr/bin/env python3
"""Wait for manifest files, then collect real Snowpipe and load-history evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from lib import (
    BLOCKED_EXTERNAL,
    FAIL,
    PASS,
    ROOT,
    evidence_path,
    load_yaml,
    manifest_stage_path,
    snowflake_connect,
    testbed_database,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--wait-seconds", type=int, default=300, help="Maximum time to wait for all manifest pipe files")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "hospitality" / "manifest.json")
    parser.add_argument("--json-output", type=Path, default=evidence_path("snowpipe-health.json"))
    return parser.parse_args()


def rows(cursor: Any) -> list[dict[str, object]]:
    columns = [item[0].lower() for item in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def normalized_state(status: object) -> str:
    if not isinstance(status, dict):
        return "UNKNOWN"
    return str(status.get("executionState") or status.get("execution_state") or "UNKNOWN").upper()


def history_for(cursor: Any, database: str, table: str, hours: int) -> list[dict[str, object]]:
    cursor.execute(
        f"SELECT FILE_NAME, LAST_LOAD_TIME, ROW_COUNT, ROW_PARSED, ERROR_COUNT, STATUS, PIPE_NAME, "
        f"BYTES_BILLED FROM TABLE({database}.INFORMATION_SCHEMA.COPY_HISTORY("
        "TABLE_NAME=>%s, START_TIME=>DATEADD('hour', -%s, CURRENT_TIMESTAMP()))) "
        "ORDER BY LAST_LOAD_TIME DESC",
        (table, hours),
    )
    return rows(cursor)


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        entities = load_yaml("hospitality_ingestion.yml")["entities"]
        expected: dict[str, set[str]] = {}
        for item in manifest["files"]:
            spec = entities[item["entity"]]
            if spec.get("snowpipe"):
                expected.setdefault(item["entity"], set()).add(manifest_stage_path(item, manifest["generation_id"]))
        if not expected:
            raise ValueError("Manifest contains no Snowpipe-managed files")

        database = testbed_database()
        hours = max(1, min(args.hours, 336))
        deadline = time.monotonic() + max(0, args.wait_seconds)
        connection = snowflake_connect()
        history_by_entity: dict[str, list[dict[str, object]]] = {}
        missing_by_entity: dict[str, list[str]] = {}
        pipe_results: list[dict[str, object]] = []

        with connection:
            cursor = connection.cursor()
            while True:
                history_by_entity = {}
                missing_by_entity = {}
                for entity, expected_files in expected.items():
                    table = str(entities[entity]["target"]).split(".")[-1]
                    history = history_for(cursor, database, table, hours)
                    matching_history = [
                        row
                        for row in history
                        if any(str(row.get("file_name") or "").endswith(path) for path in expected_files)
                    ]
                    history_by_entity[entity] = matching_history
                    observed = {str(item.get("file_name") or "") for item in matching_history}
                    missing = sorted(path for path in expected_files if not any(name.endswith(path) for name in observed))
                    if missing:
                        missing_by_entity[entity] = missing
                if not missing_by_entity or time.monotonic() >= deadline:
                    break
                time.sleep(max(1, args.poll_seconds))

            for entity, spec in entities.items():
                pipe_name = spec.get("snowpipe")
                if not pipe_name:
                    continue
                qualified = f"{database}.RAW.{pipe_name}"
                cursor.execute("SELECT SYSTEM$PIPE_STATUS(%s) AS STATUS", (qualified,))
                status_raw = cursor.fetchone()[0]
                status = json.loads(status_raw) if isinstance(status_raw, str) else status_raw
                cursor.execute(
                    f"SELECT * FROM TABLE({database}.INFORMATION_SCHEMA.VALIDATE_PIPE_LOAD("
                    "PIPE_NAME=>%s, START_TIME=>DATEADD('hour', -%s, CURRENT_TIMESTAMP())))",
                    (qualified, hours),
                )
                validation = rows(cursor)
                pipe_results.append(
                    {
                        "entity": entity,
                        "pipe": qualified,
                        "status": status,
                        "copy_history": history_by_entity.get(entity, []),
                        "expected_file_count": len(expected[entity]),
                        "missing_files": missing_by_entity.get(entity, []),
                        "validation_errors": validation,
                    }
                )
            cursor.close()

        failed = [
            item
            for item in pipe_results
            if item["missing_files"]
            or item["validation_errors"]
            or normalized_state(item["status"]) != "RUNNING"
            or any(
                int(row.get("error_count") or 0) > 0 or str(row.get("status") or "").upper() != "LOADED"
                for row in item["copy_history"]
            )
        ]
        result = {
            "status": PASS if not failed else FAIL,
            "testbed_only": True,
            "generation_id": manifest["generation_id"],
            "load_id": manifest["load_id"],
            "expected_file_count": sum(len(value) for value in expected.values()),
            "observed_file_count": sum(
                len(value) - len(missing_by_entity.get(entity, [])) for entity, value in expected.items()
            ),
            "pipes": pipe_results,
            "failed_pipe_count": len(failed),
        }
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "testbed_only": True, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
