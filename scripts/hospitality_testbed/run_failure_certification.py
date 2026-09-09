#!/usr/bin/env python3
"""Stage one approved failure fixture and capture ADE RCA without inventing a result."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from certify_failure_accuracy import compare
from lib import BLOCKED_APPROVAL, BLOCKED_EXTERNAL, FAIL, NOT_RUN, PASS, ROOT, approved, evidence_path, load_yaml, snowflake_env_missing, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=tuple(load_yaml("hospitality_failure_scenarios.yml")["scenarios"]))
    parser.add_argument("--mode", choices=("local", "live"), default="live")
    parser.add_argument("--wait-seconds", type=int, default=180, help="Maximum time to wait for asynchronous Snowpipe evidence")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--json-output", type=Path, default=evidence_path("failure-certification.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not approved():
        result = {"status": BLOCKED_APPROVAL, "scenario": args.scenario, "observed_divergence": NOT_RUN}
    elif snowflake_env_missing():
        result = {"status": BLOCKED_EXTERNAL, "scenario": args.scenario, "observed_divergence": NOT_RUN, "missing": snowflake_env_missing()}
    else:
        stage_output = evidence_path(f"failure-{args.scenario}-stage.json")
        stage = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/hospitality_testbed/stage_failure_fixture.py"),
                "--scenario",
                args.scenario,
                "--stage",
                "--mode",
                args.mode,
                "--json-output",
                str(stage_output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        stage_evidence = json.loads(stage_output.read_text(encoding="utf-8")) if stage_output.exists() else {}
        if stage.returncode or stage_evidence.get("status") != PASS:
            result = {
                "status": stage_evidence.get("status", FAIL),
                "scenario": args.scenario,
                "observed_divergence": NOT_RUN,
                "stage_error": stage_evidence.get("error") or stage_evidence.get("message") or stage.stderr[-2000:],
            }
        else:
            run_id = stage_evidence["failure_run_id"]
            certify_output = evidence_path(f"failure-{args.scenario}-ade.json")
            deadline = time.monotonic() + max(0, args.wait_seconds)
            evidence = {}
            certify = None
            while True:
                certify = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/hospitality_testbed/certify_with_ade.py"),
                        "--mode",
                        args.mode,
                        "--stage-pattern",
                        f".*failures/{args.scenario}/{run_id}/.*",
                        "--json-output",
                        str(certify_output),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                evidence = json.loads(certify_output.read_text(encoding="utf-8")) if certify_output.exists() else {}
                evidence_matches_run = run_id in json.dumps(evidence, default=str)
                if (evidence.get("first_divergence") and evidence_matches_run) or time.monotonic() >= deadline:
                    break
                time.sleep(max(1, args.poll_seconds))
            expected = load_yaml("hospitality_failure_scenarios.yml")["scenarios"][args.scenario]["expected_divergence"]
            observed = evidence.get("first_divergence") if run_id in json.dumps(evidence, default=str) else NOT_RUN
            correct = observed != NOT_RUN and observed == expected
            result = {
                "status": PASS if correct else FAIL,
                "pipeline_status": evidence.get("status", FAIL),
                "scenario": args.scenario,
                "failure_run_id": run_id,
                "expected_divergence": expected,
                "observed_divergence": observed,
                "correct": correct,
                "evidence": evidence.get("evidence", []),
                "certification_exit_code": certify.returncode,
            }
    write_json(args.json_output, result)
    if "expected_divergence" in result:
        observations_path = evidence_path("failure-observations.json")
        observations = json.loads(observations_path.read_text(encoding="utf-8")) if observations_path.exists() else {"scenarios": []}
        observations["scenarios"] = [item for item in observations.get("scenarios", []) if item.get("scenario") != args.scenario]
        observations["scenarios"].append(result)
        write_json(observations_path, observations)
        ground_truth_path = ROOT / "data" / "hospitality" / "failures" / "ground_truth.json"
        if ground_truth_path.exists():
            accuracy = compare(json.loads(ground_truth_path.read_text(encoding="utf-8")), observations)
            write_json(evidence_path("failure-accuracy.json"), accuracy)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
