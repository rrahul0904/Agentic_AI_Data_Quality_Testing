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


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def git_head() -> str | None:
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
        if item.get("certification_track") == "COCO_PARITY_CERTIFICATION"
    ]
    extensions = [
        item for item in capabilities
        if item.get("certification_track") != "COCO_PARITY_CERTIFICATION"
    ]
    unresolved = [
        {
            "id": item["id"],
            "current": item.get("ade_current"),
            "acceptance": item.get("acceptance"),
            "limitation": item.get("known_limitation"),
        }
        for item in coco
        if item.get("ade_current") not in {"implemented", "implemented_on_branch", "superior"}
    ]
    local_certified = (
        golden.get("status") == "PASS"
        and golden.get("scenario_count") == 8
        and not unresolved
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head_sha": git_head(),
        "ledger_capability_count": len(capabilities),
        "coco_capability_count": len(coco),
        "extension_capability_count": len(extensions),
        "golden_scenarios": {
            "status": golden.get("status"),
            "passed": golden.get("passed"),
            "failed": golden.get("failed"),
            "head_sha": golden.get("head_sha"),
            "evidence_fingerprint": golden.get("evidence_fingerprint"),
        },
        "unresolved_coco_capabilities": unresolved,
        "local_ci_certified": local_certified,
        "live_external_certified": False,
        "superiority_certified": False,
        "coco_parity_complete": local_certified,
        "truthfulness": {
            "extensions_do_not_gate_coco_parity": True,
            "live_external_not_inferred_from_local_tests": True,
            "superiority_not_inferred_from_implementation": True,
        },
    }
    report["certification_fingerprint"] = digest(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "head_sha": report["head_sha"],
        "local_ci_certified": report["local_ci_certified"],
        "coco_parity_complete": report["coco_parity_complete"],
        "unresolved_count": len(unresolved),
        "output": str(args.output.relative_to(ROOT)),
        "certification_fingerprint": report["certification_fingerprint"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
