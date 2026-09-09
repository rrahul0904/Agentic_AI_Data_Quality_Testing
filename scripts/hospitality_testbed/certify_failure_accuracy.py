#!/usr/bin/env python3
"""Compare known fixture divergence with actually observed ADE RCA evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import FAIL, NOT_RUN, PASS, ROOT, evidence_path, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=ROOT / "data" / "hospitality" / "failures" / "ground_truth.json")
    parser.add_argument("--observations", type=Path, default=evidence_path("failure-observations.json"))
    parser.add_argument("--json-output", type=Path, default=evidence_path("failure-accuracy.json"))
    return parser.parse_args()


def compare(ground_truth: dict, observations: dict) -> dict:
    observed = {item["scenario"]: item for item in observations.get("scenarios", [])}
    results = []
    for item in ground_truth.get("scenarios", []):
        actual = observed.get(item["scenario"])
        divergence = actual.get("observed_divergence") if actual else NOT_RUN
        correct = divergence != NOT_RUN and divergence == item["expected_divergence"]
        results.append({"scenario": item["scenario"], "expected_divergence": item["expected_divergence"], "observed_divergence": divergence, "correct": correct if divergence != NOT_RUN else None, "evidence": actual.get("evidence", []) if actual else []})
    executed = [item for item in results if item["observed_divergence"] != NOT_RUN]
    complete = len(executed) == len(results)
    status = (PASS if all(item["correct"] for item in executed) else FAIL) if complete else NOT_RUN
    accuracy = round(100 * sum(bool(item["correct"]) for item in executed) / len(executed), 2) if complete and executed else None
    return {
        "status": status,
        "executed_scenarios": len(executed),
        "total_scenarios": len(results),
        "all_scenarios_executed": complete,
        "accuracy_pct": accuracy,
        "scenarios": results,
    }


def main() -> int:
    args = parse_args()
    ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    observations = json.loads(args.observations.read_text(encoding="utf-8")) if args.observations.exists() else {"scenarios": []}
    result = compare(ground_truth, observations)
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
