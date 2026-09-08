#!/usr/bin/env python3
"""Generate four-dimensional parity ledger without binary DONE semantics."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def conformance_index(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    index: dict[str, list[str]] = {}
    for item in report.get("results", ()):
        if item.get("status") != "MATCH":
            continue
        case_id = str(item.get("id"))
        for key in (item.get("tool"), item.get("capability")):
            if key:
                index.setdefault(str(key), []).append(case_id)
    return index


def transform(ledger: dict[str, Any], behavioral: dict[str, list[str]]) -> dict[str, Any]:
    entries = []
    for index, item in enumerate(ledger.get("entries", ()), 1):
        legacy = str(item.get("status") or "")
        implemented = legacy not in {"MISSING", "NOT_APPLICABLE"}
        unit_verified = bool(item.get("tests"))
        keys = {
            str(value)
            for value in (
                item.get("reference_tool_name"),
                item.get("reference_symbol"),
                item.get("our_tool_name"),
            )
            if value
        }
        behavioral_ids = sorted({
            case_id for key in keys for case_id in behavioral.get(key, ())
        })
        external = item.get("external_dependency")
        live_verified: bool | None = None if not external else False
        if not implemented:
            status = "FAIL"
        elif external:
            status = "SKIP_EXTERNAL"
        elif unit_verified and behavioral_ids:
            status = "PASS_LOCAL"
        else:
            status = "PARTIAL"
        capability_id = item.get("capability_id") or item.get("id") or f"PARITY-{index:04d}"
        entries.append({
            "capability_id": capability_id,
            "feature": item.get("reference_tool_name") or item.get("reference_symbol") or item.get("reference_path"),
            "reference_area": item.get("reference_category"),
            "reference_path": item.get("reference_path"),
            "implementation_path": item.get("our_path"),
            "implemented": implemented,
            "unit_verified": unit_verified,
            "behaviorally_verified": bool(behavioral_ids),
            "live_verified": live_verified,
            "supported_targets": [],
            "known_differences": [item["notes"]] if item.get("notes") else [],
            "test_ids": list(item.get("tests") or ()),
            "behavioral_test_ids": behavioral_ids,
            "external_requirements": [external] if external else [],
            "legacy_status": legacy,
            "status": status,
            "expected_behavior": item.get("expected_behavior") or item.get("reference_tool_name") or item.get("reference_symbol") or item.get("reference_path"),
            "evidence": {
                "implementation": item.get("our_path"),
                "tests": list(item.get("tests") or ()),
                "behavioral_tests": behavioral_ids,
            },
            "external_dependency": external,
            "last_certified_sha": os.getenv("ADE_LAST_CERTIFIED_SHA"),
            "evidence_sha": os.getenv("GITHUB_SHA"),
        })
    return {
        "schema_version": 3,
        "status_legend": {
            "I": "Implemented",
            "U": "Unit verified",
            "B": "Behaviorally verified",
            "L": "Live verified",
        },
        "reference": ledger.get("generated_for_reference"),
        "target": ledger.get("target"),
        "dimensions": {
            "implemented": sum(item["implemented"] for item in entries),
            "unit_verified": sum(item["unit_verified"] for item in entries),
            "behaviorally_verified": sum(item["behaviorally_verified"] for item in entries),
            "live_verified": sum(item["live_verified"] is True for item in entries),
            "live_not_applicable": sum(item["live_verified"] is None for item in entries),
        },
        "entries": entries,
    }


def write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# Altimate Behavioral Parity Ledger 2.0",
        "",
        "Binary DONE semantics are intentionally not used.",
        "",
        "| Dimension | Count |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {name} | {count} |"
        for name, count in result["dimensions"].items()
    )
    lines.extend([
        "",
        "| Capability | Feature | Status | Implemented | Unit | Behavioral | Live | External |",
        "|---|---|---|:---:|:---:|:---:|:---:|---|",
    ])
    for item in result["entries"]:
        live = "N/A" if item["live_verified"] is None else ("YES" if item["live_verified"] else "NO")
        feature = str(item["feature"]).replace("|", "/")
        external = str(item.get("external_dependency") or "").replace("|", "/")
        lines.append(
            f"| {item['capability_id']} | {feature} | {item['status']} | "
            f"{'YES' if item['implemented'] else 'NO'} | "
            f"{'YES' if item['unit_verified'] else 'NO'} | "
            f"{'YES' if item['behaviorally_verified'] else 'NO'} | {live} | {external} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "specs" / "ALTIMATE_FULL_PARITY_LEDGER.json"))
    parser.add_argument("--conformance", default=str(ROOT / "artifacts" / "conformance-report.json"))
    parser.add_argument("--json-output", default=str(ROOT / "specs" / "ALTIMATE_PARITY_LEDGER_V2.json"))
    parser.add_argument("--md-output", default=str(ROOT / "specs" / "ALTIMATE_PARITY_LEDGER_V2.md"))
    args = parser.parse_args()

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = transform(source, conformance_index(Path(args.conformance)))
    json_path = Path(args.json_output)
    markdown_path = Path(args.md_output)
    json_path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    write_markdown(result, markdown_path)
    print(json.dumps(result["dimensions"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
