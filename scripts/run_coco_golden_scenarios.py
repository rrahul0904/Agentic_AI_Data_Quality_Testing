#!/usr/bin/env python3
"""Execute the eight deterministic CoCo golden scenarios and emit evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "specs" / "COCO_GOLDEN_SCENARIOS.json"
DEFAULT_REPORT = ROOT / "reports" / "certification" / "coco_golden_scenarios.json"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def head_sha() -> str | None:
    value = os.getenv("GITHUB_HEAD_SHA") or os.getenv("GITHUB_SHA")
    if value:
        return value
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
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scenario", action="append", default=[])
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    scenarios = list(spec["scenarios"])
    requested = set(args.scenario)
    if requested:
        scenarios = [item for item in scenarios if item["id"] in requested]
        missing = requested - {item["id"] for item in scenarios}
        if missing:
            raise SystemExit("unknown scenario(s): " + ", ".join(sorted(missing)))

    results = []
    overall = "PASS"
    for scenario in scenarios:
        command = [str(item) for item in scenario["command"]]
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        status = "PASS" if completed.returncode == 0 else "FAIL"
        if status != scenario.get("expected", "PASS"):
            overall = "FAIL"
        results.append(
            {
                "id": scenario["id"],
                "title": scenario["title"],
                "status": status,
                "expected": scenario.get("expected", "PASS"),
                "returncode": completed.returncode,
                "duration_ms": duration_ms,
                "capabilities": scenario.get("capabilities", []),
                "external_required": bool(scenario.get("external_required", False)),
                "certification_track": scenario.get("certification_track", "COCO_PARITY_CERTIFICATION"),
                "command": command,
                "stdout_tail": completed.stdout[-12000:],
                "stderr_tail": completed.stderr[-12000:],
            }
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head_sha": head_sha(),
        "spec_version": spec.get("version"),
        "scenario_count": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] != "PASS" for item in results),
        "status": overall,
        "results": results,
    }
    report["evidence_fingerprint"] = digest(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "scenario_count": report["scenario_count"],
        "passed": report["passed"],
        "failed": report["failed"],
        "head_sha": report["head_sha"],
        "report": str(args.report.relative_to(ROOT)),
        "evidence_fingerprint": report["evidence_fingerprint"],
    }, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
