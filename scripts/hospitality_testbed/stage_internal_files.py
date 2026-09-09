#!/usr/bin/env python3
"""PUT manifest-listed files onto the isolated Snowflake internal stage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, evidence_path, manifest_stage_path, snowflake_connect, testbed_database, update_state, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "hospitality")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json-output", type=Path, default=evidence_path("internal-stage.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    manifest_path = (args.manifest or data_dir / "manifest.json").resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        connection = snowflake_connect()
        staged = []
        with connection:
            cursor = connection.cursor()
            for item in manifest["files"]:
                path = (data_dir / item["file"]).resolve()
                if not path.is_relative_to(data_dir) or not path.is_file():
                    raise ValueError(f"Unsafe or missing manifest file: {path}")
                staged_path = Path(manifest_stage_path(item, manifest["generation_id"]))
                parent = staged_path.parent.as_posix()
                sql = f"PUT 'file://{str(path).replace(chr(39), chr(39) * 2)}' @{testbed_database(mutation=True)}.RAW.STAGE_HOSPITALITY_INTERNAL/{parent}/ AUTO_COMPRESS=FALSE OVERWRITE=FALSE"
                cursor.execute(sql)
                staged.append(staged_path.as_posix())
            cursor.close()
        result = {"status": PASS, "testbed_only": True, "generation_id": manifest["generation_id"], "files_staged": len(staged)}
        update_state(files_staged=len(staged), mode="local")
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "testbed_only": True, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "testbed_only": True, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
