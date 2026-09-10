#!/usr/bin/env python3
"""Build a truthful CoCo parity certification report from ledger + golden evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "specs" / "ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json"
GOLDEN = ROOT / "reports" / "certification" / "coco_golden_scenarios.json"
DEFAULT_OUTPUT = ROOT / "reports" / "certification" / "coco_certification_report.json"
COCO_TRACK = "COCO_PARITY_CERTIFICATION"
IMPLEMENTED_STATES = {"implemented", "implemented_on_branch", "superior"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def git_head() -> str | None:
    if os.getenv("GITHUB_HEAD_SHA"):
        return os.getenv("GITHUB_HEAD_SHA")
    if os.getenv("GITHUB_SHA"):
        return os.getenv("GITHUB_SHA")
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _passed_scenario_capabilities(golden: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    certified: set[str] = set()
    evidence: dict[str, str] = {}
    for scenario in golden.get("results") or []:
        if scenario.get("status") != "PASS":
            continue
        if scenario.get("certification_track", COCO_TRACK) != COCO_TRACK:
            continue
        scenario_id = str(scenario.get("id") or "")
        for capability_id in scenario.get("capabilities") or []:
            capability = str(capability_id)
            certified.add(capability)
            evidence[capability] = scenario_id
    return certified, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    capabilities = list(ledger.get("capabilities", []))
    coco = [
        item for item in capabilities
        if item.get("certification_track") == COCO_TRACK
    ]
    extensions = [
        item for item in capabilities
        if item.get("certification_track") != COCO_TRACK
    ]

    golden_certified, scenario_by_capability = _passed_scenario_capabilities(golden)
    declared_unresolved = [
        {
            "id": item["id"],
            "current": item.get("ade_current"),
            "acceptance": item.get("acceptance"),
            "limitation": item.get("known_limitation"),
        }
        for item in coco
        if item.get("ade_current") not in IMPLEMENTED_STATES
    ]
    effective_unresolved = [
        {
            "id": item["id"],
            "current": item.get("ade_current"),
            "acceptance": item.get("acceptance"),
            "limitation": item.get("known_limitation"),
            "reason": "not declared implemented and not certified by a passing CoCo golden scenario",
        }
        for item in coco
        if item.get("ade_current") not in IMPLEMENTED_STATES
        and item.get("id") not in golden_certified
    ]
    stale_declarations = [
        {
            "id": item["id"],
            "declared": item.get("ade_current"),
            "effective": "implemented_on_branch",
            "scenario": scenario_by_capability[item["id"]],
        }
        for item in coco
        if item.get("ade_current") not in IMPLEMENTED_STATES
        and item.get("id") in golden_certified
    ]

    all_golden_passed = (
        golden.get("status") == "PASS"
        and golden.get("scenario_count") == 8
        and golden.get("failed") == 0
        and golden.get("passed") == 8
    )
    local_certified = all_golden_passed and not effective_unresolved
    head = git_head()
    golden_head = golden.get("head_sha")
    head_matches = bool(head and golden_head and head == golden_head)

    report = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head_sha": head,
        "ledger_capability_count": len(capabilities),
        "coco_capability_count": len(coco),
        "extension_capability_count": len(extensions),
        "golden_scenarios": {
            "status": golden.get("status"),
            "passed": golden.get("passed"),
            "failed": golden.get("failed"),
            "head_sha": golden_head,
            "head_matches_report": head_matches,
            "evidence_fingerprint": golden.get("evidence_fingerprint"),
        },
        "declared_unresolved_coco_capabilities": declared_unresolved,
        "stale_ledger_declarations": stale_declarations,
        "golden_certified_coco_capabilities": sorted(golden_certified),
        "effective_unresolved_coco_capabilities": effective_unresolved,
        # Backward-compatible key now represents the effective release blockers.
        "unresolved_coco_capabilities": effective_unresolved,
        "local_ci_certified": local_certified,
        "live_external_certified": False,
        "superiority_certified": False,
        "coco_parity_complete": local_certified,
        "truthfulness": {
            "extensions_do_not_gate_coco_parity": True,
            "live_external_not_inferred_from_local_tests": True,
            "superiority_not_inferred_from_implementation": True,
            "golden_scenario_pass_may_certify_local_implementation": True,
            "declared_and_effective_status_reported_separately": True,
            "exact_head_match_reported_separately": True,
        },
    }
    report["certification_fingerprint"] = digest(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "head_sha": report["head_sha"],
        "golden_head_sha": golden_head,
        "head_matches_golden": head_matches,
        "local_ci_certified": report["local_ci_certified"],
        "coco_parity_complete": report["coco_parity_complete"],
        "declared_unresolved_count": len(declared_unresolved),
        "stale_declaration_count": len(stale_declarations),
        "effective_unresolved_count": len(effective_unresolved),
        "output": str(args.output.relative_to(ROOT)),
        "certification_fingerprint": report["certification_fingerprint"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
