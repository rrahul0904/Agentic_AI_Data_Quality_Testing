#!/usr/bin/env python3
"""Reconcile manifest, files, COPY history, and RAW counts by generation/load identity."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from lib import BLOCKED_EXTERNAL, FAIL, NOT_RUN, PASS, ROOT, evidence_path, load_yaml, manifest_stage_path, snowflake_connect, snowflake_env_missing, testbed_database, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "hospitality" / "manifest.json")
    parser.add_argument("--offline", action="store_true", help="Reconcile manifest to local files only")
    parser.add_argument("--json-output", type=Path, default=evidence_path("reconciliation.json"))
    return parser.parse_args()


def local_count(path: Path, file_format: str) -> int:
    if file_format == "csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(1 for _ in csv.reader(handle)) - 1
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).metadata.num_rows


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        data_dir = args.manifest.parent
        generated: defaultdict[str, int] = defaultdict(int)
        files: defaultdict[str, int] = defaultdict(int)
        stage_files: defaultdict[str, set[str]] = defaultdict(set)
        for item in manifest["files"]:
            generated[item["entity"]] += int(item["row_count"])
            files[item["entity"]] += local_count(data_dir / item["file"], item["format"])
            stage_files[item["entity"]].add(manifest_stage_path(item, manifest["generation_id"]))
        offline = args.offline or bool(snowflake_env_missing())
        warehouse: dict[str, dict[str, int]] = {}
        warehouse_status = NOT_RUN
        blocker = None
        if not offline:
            database = testbed_database()
            entities = load_yaml("hospitality_ingestion.yml")["entities"]
            connection = snowflake_connect()
            with connection:
                cursor = connection.cursor()
                for entity, spec in entities.items():
                    cursor.execute(f"SELECT COUNT(*) FROM {database}.{spec['target']} WHERE _GENERATION_ID=%s AND _LOAD_ID=%s", (manifest["generation_id"], manifest["load_id"]))
                    raw_count = int(cursor.fetchone()[0])
                    cursor.execute(
                        f"SELECT FILE_NAME, ROW_PARSED, ROW_COUNT, ERROR_COUNT FROM TABLE("
                        f"{database}.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME=>%s, "
                        "START_TIME=>DATEADD('day',-14,CURRENT_TIMESTAMP())))",
                        (spec["target"].split(".")[1],),
                    )
                    matching = [
                        row
                        for row in cursor.fetchall()
                        if any(str(row[0] or "").endswith(path) for path in stage_files[entity])
                    ]
                    parsed = sum(int(row[1] or 0) for row in matching)
                    loaded = sum(int(row[2] or 0) for row in matching)
                    rejected = sum(int(row[3] or 0) for row in matching)
                    warehouse[entity] = {
                        "copy_parsed_rows": parsed,
                        "copy_loaded_rows": loaded,
                        "raw_rows": raw_count,
                        "rejected_rows": rejected,
                        "history_files": len(matching),
                        "expected_files": len(stage_files[entity]),
                    }
                cursor.close()
            warehouse_status = PASS
        elif snowflake_env_missing():
            blocker = f"{BLOCKED_EXTERNAL}: missing {', '.join(snowflake_env_missing())}"
        results = []
        for entity in sorted(generated):
            item: dict[str, Any] = {"entity": entity, "generated_rows": generated[entity], "local_file_rows": files[entity], "copy_parsed_rows": NOT_RUN, "copy_loaded_rows": NOT_RUN, "raw_rows": NOT_RUN, "rejected_rows": NOT_RUN}
            item.update(warehouse.get(entity, {}))
            item["status"] = PASS if generated[entity] == files[entity] and (not warehouse or (item["raw_rows"] == generated[entity] and item["copy_loaded_rows"] == generated[entity] and item["rejected_rows"] == 0 and item["history_files"] == item["expected_files"])) else FAIL
            results.append(item)
        status = PASS if all(item["status"] == PASS for item in results) else FAIL
        result = {"status": status, "scope": "LOCAL_MANIFEST_FILES" if offline else "END_TO_END_SNOWFLAKE", "warehouse_status": warehouse_status, "external_blocker": blocker, "generation_id": manifest["generation_id"], "load_id": manifest["load_id"], "entities": results}
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
