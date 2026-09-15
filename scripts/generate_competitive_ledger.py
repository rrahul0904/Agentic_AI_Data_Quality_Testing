#!/usr/bin/env python3
"""Generate the competitive capability ledger only from explicit CI evidence inputs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentic_data_platform.certification.competitive import write_competitive_ledger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", default="artifacts/competitive/capability-ledger.json")
    parser.add_argument("--local-gate-passed", action="store_true")
    args = parser.parse_args()
    workflow = {
        "workflow": os.getenv("GITHUB_WORKFLOW"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "event": os.getenv("GITHUB_EVENT_NAME"),
    }
    workflow = {key: value for key, value in workflow.items() if value}
    path = write_competitive_ledger(
        args.output,
        args.commit_sha,
        local_gate_passed=args.local_gate_passed,
        workflow=workflow,
    )
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())