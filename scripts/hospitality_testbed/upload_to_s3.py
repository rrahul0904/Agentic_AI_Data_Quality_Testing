#!/usr/bin/env python3
"""Upload manifest-listed testbed files to S3 using the ambient AWS credential chain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, PASS, ROOT, aws_env_missing, env, evidence_path, manifest_stage_path, update_state, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "hospitality")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json-output", type=Path, default=evidence_path("s3-upload.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = aws_env_missing()
    if missing:
        result = {"status": BLOCKED_EXTERNAL, "error": f"Missing {', '.join(missing)}"}
    else:
        try:
            import boto3
            data_dir = args.data_dir.resolve()
            manifest = json.loads((args.manifest or data_dir / "manifest.json").read_text(encoding="utf-8"))
            bucket = env("ADE_TESTBED_S3_BUCKET") or ""
            prefix = (env("ADE_TESTBED_S3_PREFIX", "hospitality") or "hospitality").strip("/")
            client = boto3.client("s3", region_name=env("AWS_REGION"))
            uploaded = []
            for item in manifest["files"]:
                path = (data_dir / item["file"]).resolve()
                if not path.is_relative_to(data_dir) or not path.is_file():
                    raise ValueError(f"Unsafe or missing manifest file: {path}")
                key = f"{prefix}/{manifest_stage_path(item, manifest['generation_id'])}"
                client.upload_file(str(path), bucket, key, ExtraArgs={"Metadata": {"generation-id": manifest["generation_id"], "load-id": manifest["load_id"]}})
                uploaded.append(key)
            result = {"status": PASS, "testbed_only": True, "bucket": bucket, "prefix": prefix, "generation_id": manifest["generation_id"], "files_uploaded": len(uploaded)}
            update_state(files_uploaded=len(uploaded), mode="live")
        except ImportError:
            result = {"status": BLOCKED_EXTERNAL, "error": "boto3 is not installed"}
        except Exception as exc:
            result = {"status": FAIL, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
