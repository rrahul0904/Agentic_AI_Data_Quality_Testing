#!/usr/bin/env python3
"""Render generation-bounded COPY INTO commands from ingestion metadata."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from lib import FAIL, PASS, ROOT, evidence_path, load_yaml, manifest_stage_path, testbed_database, write_json

SAFE_FILE = re.compile(r"^[A-Za-z0-9_./=-]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live"), default="local")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "hospitality" / "manifest.json")
    parser.add_argument("--output", type=Path, default=evidence_path("copy-commands.sql"))
    parser.add_argument("--json-output", type=Path, default=evidence_path("copy-rendering.json"))
    return parser.parse_args()


def copy_commands(manifest: dict[str, Any], mode: str, *, exclude_snowpipe: bool = False) -> list[dict[str, Any]]:
    database = testbed_database()
    entities = load_yaml("hospitality_ingestion.yml")["entities"]
    stage = "STAGE_HOSPITALITY_INTERNAL" if mode == "local" else "STAGE_HOSPITALITY_S3"
    commands: list[dict[str, str]] = []
    for item in manifest["files"]:
        relative = item["file"]
        if not SAFE_FILE.fullmatch(relative):
            raise ValueError(f"Unsafe manifest file path: {relative!r}")
        spec = entities[item["entity"]]
        if exclude_snowpipe and spec.get("snowpipe"):
            continue
        path = Path(manifest_stage_path(item, manifest["generation_id"]))
        parent = path.parent.as_posix()
        sql = f"""COPY INTO {database}.{spec['target']}
FROM @{database}.RAW.{stage}/{parent}/
FILES = ('{path.name}')
FILE_FORMAT = (FORMAT_NAME = '{database}.RAW.{spec['file_format']}')
MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
INCLUDE_METADATA = (_SOURCE_FILE = METADATA$FILENAME, _SOURCE_ROW_NUMBER = METADATA$FILE_ROW_NUMBER, _INGESTED_AT = METADATA$START_SCAN_TIME)
ON_ERROR = '{spec.get('on_error', 'ABORT_STATEMENT')}'
PURGE = FALSE
FORCE = FALSE;"""
        commands.append(
            {
                "entity": item["entity"],
                "file": relative,
                "stage_file": path.as_posix(),
                "expected_rows": int(item["row_count"]),
                "sql": sql,
            }
        )
    return commands


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        commands = copy_commands(manifest, args.mode)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n\n".join(f"-- entity={item['entity']} file={item['file']}\n{item['sql']}" for item in commands) + "\n", encoding="utf-8")
        result = {"status": PASS, "mode": args.mode, "generation_id": manifest["generation_id"], "command_count": len(commands), "output": str(args.output)}
    except Exception as exc:
        result = {"status": FAIL, "mode": args.mode, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
