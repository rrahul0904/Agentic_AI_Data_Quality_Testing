#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.tools.builtin import build_tool_registry


ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path(os.getenv("ADE_DEMO_PROJECT", ROOT / "hospitality-snowflake-data-platform"))
DATABASE = Path(os.getenv("ADE_INVESTIGATION_DATABASE", ROOT / ".ade" / "agentic-investigations.db"))


def print_report(label: str, report: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"incident                  {report['incident_id']}")
    print(f"state                     {report['state']}")
    print(f"mode                      {report['mode']}")
    print(f"first divergence          {report['first_divergence']}")
    print(f"root cause                {report['root_cause']}")
    print(f"root cause confidence     {report['root_cause_confidence']:.2f}")
    print(f"blast radius              {len(report['blast_radius'])} assets")
    print(f"certification             {report['certification']}")
    print("agent timeline")
    for item in report["agent_results"]:
        print(f"  {item['role']:20} {item['status']:12} {item['claim'][:90]}")
    print("hypotheses")
    for item in report["hypotheses"]:
        if item["status"] in {"SUPPORTED", "REJECTED"}:
            print(f"  {item['status']:12} {item['name']}")
    print("evidence")
    for item in report["evidence"]:
        print(f"  {item['evidence_id']} {item['tier']} {item['kind']:18} {item['summary']}")


def main() -> None:
    service = SupervisorAgent(build_tool_registry(), InvestigationStore(DATABASE), PROJECT)
    pending = service.investigate("watermark_defect")
    pending_public = service.public_report(pending.incident_id)
    print_report("AGENTIC INCIDENT · HUMAN APPROVAL REQUIRED", pending_public)
    if pending_public["state"] != "AWAITING_APPROVAL":
        raise SystemExit("flagship investigation did not reach approval boundary")

    resolved = service.approve_and_execute(pending.incident_id, approved_by="demo-operator")
    resolved_public = service.public_report(resolved.incident_id)
    print_report("APPROVED RECOVERY · VERIFIED", resolved_public)
    print("verification")
    print(json.dumps(resolved_public["verification_result"], indent=2, sort_keys=True))
    if resolved_public["state"] != "RESOLVED" or resolved_public["certification"] != "CERTIFIED":
        raise SystemExit("agentic flagship demo failed")
    print("\nAGENTIC FLAGSHIP DEMO: PASS")
    print("NOTE: external Airflow/Snowflake mutations were not claimed; this run is LOCAL_PROVING_GROUND.")


if __name__ == "__main__":
    main()
