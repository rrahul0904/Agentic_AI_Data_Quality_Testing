from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from scripts.check_capability_superiority import DEFAULT_LEDGER, load_ledger, validate


DEFAULT_OUTPUT_DIR = Path("artifacts/certification")


def _head_sha() -> str:
    configured = os.getenv("GITHUB_SHA")
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _certification(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("certification")
    if isinstance(raw, dict):
        return raw
    return {}


def _entry(item: dict[str, Any]) -> dict[str, Any]:
    certification = _certification(item)
    classification = str(item["classification"])
    live_default = "NOT_RUN_EXTERNAL" if classification == "ADE_EXTENSION" else "NOT_REQUIRED"
    return {
        "id": item["id"],
        "classification": classification,
        "implementation_status": item["ade_current"],
        "local_certification": certification.get("local", "NOT_CERTIFIED"),
        "live_certification": certification.get("live", live_default),
        "release_blocking": bool(item["release_blocking"]),
        "tests": certification.get("tests", []),
        "implementation_files": certification.get("implementation_files", []),
        "evidence": certification.get("evidence", []),
        "known_limitations": [
            value
            for value in (
                item.get("known_limitation"),
                certification.get("known_limitation"),
            )
            if value
        ],
    }


def _report(payload: dict[str, Any], *, scope: str, head_sha: str) -> dict[str, Any]:
    result = validate(payload, scope=scope, require_coco_parity=False)
    entries = [
        _entry(item)
        for item in payload["capabilities"]
        if (
            scope == "extensions"
            and item["classification"] == "ADE_EXTENSION"
            or scope == "coco"
            and item["classification"] in {"COCO_CORE", "COCO_WORKFLOW"}
        )
    ]
    release_blockers = []
    if scope == "coco":
        release_blockers = validate(
            payload,
            scope="coco",
            require_coco_parity=True,
        )["release_blockers"]
    return {
        "head_sha": head_sha,
        "scope": scope,
        "status": "PASS" if not release_blockers and result["status"] == "PASS" else "INCOMPLETE",
        "summary": {
            "capability_count": len(entries),
            "by_classification": result["by_classification"],
            "scoped_by_current": result["scoped_by_current"],
            "scoped_by_live_certification": result["scoped_by_live_certification"],
        },
        "release_blockers": release_blockers,
        "capabilities": entries,
    }


def _markdown(report: dict[str, Any], title: str) -> str:
    summary = report["summary"]
    lines = [
        f"# {title}",
        "",
        f"- HEAD: `{report['head_sha']}`",
        f"- Status: **{report['status']}**",
        f"- Capabilities: {summary['capability_count']}",
        f"- Implementation states: `{json.dumps(summary['scoped_by_current'], sort_keys=True)}`",
        f"- Live states: `{json.dumps(summary['scoped_by_live_certification'], sort_keys=True)}`",
        "",
        "## Release blockers",
        "",
    ]
    blockers = report["release_blockers"]
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- None")
    lines.extend(["", "## Capabilities", ""])
    for item in report["capabilities"]:
        lines.append(
            f"- `{item['id']}` — {item['classification']} — "
            f"{item['implementation_status']} — local={item['local_certification']} — "
            f"live={item['live_certification']}"
        )
    return "\n".join(lines) + "\n"


def generate(ledger: Path, output_dir: Path) -> tuple[Path, Path]:
    payload = load_ledger(ledger)
    head_sha = _head_sha()
    output_dir.mkdir(parents=True, exist_ok=True)

    coco = _report(payload, scope="coco", head_sha=head_sha)
    extensions = _report(payload, scope="extensions", head_sha=head_sha)

    coco_json = output_dir / "coco_parity_report.json"
    extension_json = output_dir / "snowflake_extensions_report.json"
    coco_json.write_text(json.dumps(coco, indent=2, sort_keys=True) + "\n")
    extension_json.write_text(json.dumps(extensions, indent=2, sort_keys=True) + "\n")
    (output_dir / "coco_parity_report.md").write_text(
        _markdown(coco, "ADE CoCo Parity Certification"),
    )
    (output_dir / "snowflake_extensions_report.md").write_text(
        _markdown(extensions, "ADE Snowflake/Cortex Extension Certification"),
    )
    return coco_json, extension_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    coco, extensions = generate(args.ledger, args.output_dir)
    print(json.dumps({"coco": str(coco), "extensions": str(extensions)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
