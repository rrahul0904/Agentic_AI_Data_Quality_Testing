#!/usr/bin/env python3
"""Assemble available evidence into machine-readable and Markdown final reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import NOT_RUN, PASS, evidence_path, write_json

SECTIONS = {
    "generation": "generation.json",
    "file_validation": "file-validation.json",
    "internal_staging": "internal-stage.json",
    "s3_upload": "s3-upload.json",
    "copy": "copy-results.json",
    "snowpipe": "snowpipe-health.json",
    "streams": "stream-health.json",
    "dbt": "dbt-results.json",
    "data_quality": "quality.json",
    "snowflake_data_quality": "snowflake-quality.json",
    "reconciliation": "reconciliation.json",
    "ade_certification": "ade-certification.json",
    "failure_scenarios": "failure-certification.json",
    "failure_accuracy": "failure-accuracy.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=evidence_path("placeholder").parent)
    parser.add_argument("--json-output", type=Path, default=evidence_path("final-report.json"))
    parser.add_argument("--markdown-output", type=Path, default=evidence_path("final-report.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sections = {}
    blockers = []
    for section, filename in SECTIONS.items():
        path = args.artifact_dir / filename
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": NOT_RUN}
        sections[section] = value
        if value.get("status") in {"BLOCKED_EXTERNAL", "BLOCKED_APPROVAL"}:
            blockers.append({"section": section, "status": value["status"], "error": value.get("error") or value.get("message")})
    local_required = ("generation", "file_validation", "data_quality", "reconciliation")
    local_pass = all(sections[name].get("status") == PASS for name in local_required)
    live_required = (
        "s3_upload",
        "copy",
        "snowpipe",
        "streams",
        "dbt",
        "snowflake_data_quality",
        "reconciliation",
        "ade_certification",
        "failure_scenarios",
    )
    live_pass = all(sections[name].get("status") == PASS for name in live_required)
    verdict = "FULLY_CERTIFIED" if local_pass and live_pass else ("IMPLEMENTATION_COMPLETE_EXTERNAL_CERTIFICATION_PENDING" if local_pass else "LOCAL_VERIFICATION_INCOMPLETE")
    result = {"status": PASS if local_pass else "FAIL", "verdict": verdict, "sections": sections, "external_blockers": blockers}
    write_json(args.json_output, result)
    lines = ["# Hospitality Snowflake testbed report", "", f"Final verdict: **{verdict}**", "", "| Area | Status |", "| --- | --- |"]
    lines.extend(f"| {name.replace('_', ' ').title()} | {value.get('status', NOT_RUN)} |" for name, value in sections.items())
    if blockers:
        lines.extend(("", "## External blockers", ""))
        lines.extend(f"- {item['section']}: {item['status']} — {item.get('error') or 'external action required'}" for item in blockers)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if local_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
