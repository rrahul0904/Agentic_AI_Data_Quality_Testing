#!/usr/bin/env python3
"""Run the reproducible local or live hospitality flow while preserving external blockers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from lib import BLOCKED_EXTERNAL, FAIL, NOT_RUN, PASS, ROOT, aws_env_missing, evidence_path, snowflake_env_missing, update_state, utc_now, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live"), default="local")
    parser.add_argument("--preset", choices=("tiny", "small", "medium", "large"), default="tiny")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--consume-streams", action="store_true", help="Explicitly request approval-gated CDC stream consumption")
    parser.add_argument("--json-output", type=Path, default=evidence_path("e2e.json"))
    return parser.parse_args()


def run(name: str, script: str, *arguments: str, artifact: str | None = None) -> dict:
    output = evidence_path(artifact or f"e2e-{name}.json")
    output.unlink(missing_ok=True)
    command = [sys.executable, str(ROOT / "scripts" / "hospitality_testbed" / script), *arguments, "--json-output", str(output)]
    process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if output.exists():
        value = json.loads(output.read_text(encoding="utf-8"))
    else:
        value = {"status": FAIL, "error": (process.stderr or process.stdout)[-2000:]}
    value["exit_code"] = process.returncode
    return value


def main() -> int:
    args = parse_args()
    started = utc_now()
    for name in (
        "generation.json",
        "file-validation.json",
        "copy-rendering.json",
        "quality.json",
        "internal-stage.json",
        "s3-upload.json",
        "copy-results.json",
        "snowpipe-health.json",
        "stream-health.json",
        "dbt-results.json",
        "snowflake-quality.json",
        "reconciliation.json",
        "ade-certification.json",
        "final-report.json",
        "final-report.md",
    ):
        evidence_path(name).unlink(missing_ok=True)
    steps = {}
    steps["generation"] = run("generation", "generate_data.py", "--preset", args.preset, "--seed", str(args.seed), artifact="generation.json")
    if steps["generation"].get("status") == PASS:
        steps["file_validation"] = run("file-validation", "validate_files.py", artifact="file-validation.json")
    else:
        steps["file_validation"] = {"status": NOT_RUN, "reason": "generation failed"}
    if steps["file_validation"].get("status") == PASS:
        steps["copy_rendering"] = run("copy-rendering", "render_copy_commands.py", "--mode", args.mode, artifact="copy-rendering.json")
        steps["local_quality"] = run("quality", "validate_pipeline.py", artifact="quality.json")
        steps["local_reconciliation"] = run("reconciliation", "reconcile_pipeline.py", "--offline", artifact="reconciliation.json")
    else:
        for name in ("copy_rendering", "local_quality", "local_reconciliation"):
            steps[name] = {"status": NOT_RUN, "reason": "file validation did not pass"}

    local_names = ("generation", "file_validation", "copy_rendering", "local_quality", "local_reconciliation")
    local_pass = all(steps[name].get("status") == PASS for name in local_names)
    blockers = []
    snowflake_missing = snowflake_env_missing()
    aws_missing = aws_env_missing() if args.mode == "live" else []
    if not local_pass:
        steps["snowflake_pipeline"] = {"status": NOT_RUN, "reason": "local prerequisites did not pass"}
    elif snowflake_missing or aws_missing:
        blocker = {"status": BLOCKED_EXTERNAL, "snowflake_missing": snowflake_missing, "aws_missing": aws_missing}
        steps["snowflake_pipeline"] = blocker
        blockers.append(blocker)
    else:
        steps["bootstrap"] = run("bootstrap", "bootstrap_snowflake.py", "--mode", args.mode)
        if steps["bootstrap"].get("status") != PASS:
            steps["ingestion"] = {"status": NOT_RUN, "reason": "Snowflake bootstrap did not pass"}
            ingestion_pass = False
        elif args.mode == "local":
            steps["stage"] = run("stage", "stage_internal_files.py", artifact="internal-stage.json")
            if steps["stage"].get("status") == PASS:
                steps["load"] = run("load", "run_copy_loads.py", "--mode", "local", artifact="copy-results.json")
            else:
                steps["load"] = {"status": NOT_RUN, "reason": "internal staging did not pass"}
            ingestion_pass = steps["stage"].get("status") == PASS and steps["load"].get("status") == PASS
        else:
            steps["upload"] = run("upload", "upload_to_s3.py", artifact="s3-upload.json")
            if steps["upload"].get("status") == PASS:
                steps["reference_copy"] = run("reference-copy", "run_copy_loads.py", "--mode", "live", "--exclude-snowpipe", artifact="copy-results.json")
                steps["snowpipe"] = run("snowpipe", "monitor_snowpipe.py", artifact="snowpipe-health.json")
            else:
                steps["reference_copy"] = {"status": NOT_RUN, "reason": "S3 upload did not pass"}
                steps["snowpipe"] = {"status": NOT_RUN, "reason": "S3 upload did not pass"}
            ingestion_pass = all(steps[name].get("status") == PASS for name in ("upload", "reference_copy", "snowpipe"))

        if ingestion_pass:
            steps["streams"] = run("streams", "monitor_streams.py", artifact="stream-health.json")
            steps["cdc"] = (
                run("cdc", "consume_streams.py", "--execute")
                if args.consume_streams
                else {"status": NOT_RUN, "reason": "Pass --consume-streams and set ADE_TESTBED_MUTATION_APPROVED=true"}
            )
            steps["dbt"] = run("dbt", "run_dbt.py", artifact="dbt-results.json")
            steps["snowflake_quality"] = run("snowflake-quality", "run_snowflake_dq.py", artifact="snowflake-quality.json")
            steps["reconciliation"] = run("warehouse-reconciliation", "reconcile_pipeline.py", artifact="reconciliation.json")
            manifest = json.loads((ROOT / "data" / "hospitality" / "manifest.json").read_text(encoding="utf-8"))
            expected_reservations = sum(int(item["row_count"]) for item in manifest["files"] if item["entity"] == "reservations")
            steps["ade"] = run(
                "ade",
                "certify_with_ade.py",
                "--mode",
                args.mode,
                "--generation-id",
                manifest["generation_id"],
                "--expected-loaded-rows",
                str(expected_reservations),
                artifact="ade-certification.json",
            )
        else:
            for name in ("streams", "cdc", "dbt", "snowflake_quality", "reconciliation", "ade"):
                steps[name] = {"status": NOT_RUN, "reason": "ingestion did not pass"}
    required_steps = [value for name, value in steps.items() if name != "cdc" or args.consume_streams]
    status = (BLOCKED_EXTERNAL if local_pass and blockers else (PASS if local_pass and all(value.get("status") == PASS for value in required_steps) else FAIL))
    steps["final_report"] = run("final-report", "generate_final_report.py", artifact="final-report.json")
    if steps["final_report"].get("status") == FAIL:
        status = FAIL
    result = {"status": status, "mode": args.mode, "started_at": started, "completed_at": utc_now(), "steps": steps, "external_blockers": blockers}
    write_json(args.json_output, result)
    update_state(mode=args.mode, started_at=started, completed_at=result["completed_at"], e2e_status=status)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if status == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
