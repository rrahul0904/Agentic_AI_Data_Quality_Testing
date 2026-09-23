#!/usr/bin/env python3
"""Classify semantic manifest diffs into production change-risk levels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def classify(diff: dict[str, Any]) -> dict[str, Any]:
    if diff.get("status") == "UNCHANGED":
        return {
            "risk": "none",
            "approval_required": False,
            "reasons": [],
            "changed_sections": [],
        }

    reasons: list[str] = []
    risk = "low"

    grain = diff.get("details", {}).get("grain", {})
    if grain.get("modified") or grain.get("removed"):
        risk = "breaking"
        reasons.append("semantic grain changed")

    for section in ("metrics", "facts", "dimensions", "time_dimensions"):
        changes = diff.get("details", {}).get(section, {})
        if changes.get("removed"):
            risk = "breaking"
            reasons.append(f"{section} removed: {', '.join(changes['removed'])}")
        if changes.get("modified") and risk != "breaking":
            risk = "high"
            reasons.append(f"{section} definitions modified: {', '.join(changes['modified'])}")
        if changes.get("added") and risk == "low":
            reasons.append(f"{section} added: {', '.join(changes['added'])}")

    vq = diff.get("details", {}).get("verified_queries", {})
    if (vq.get("removed") or vq.get("modified")) and risk not in ("breaking",):
        risk = "medium" if risk == "low" else risk
        reasons.append("verified query coverage changed")

    consumers = diff.get("details", {}).get("consumers", {})
    if consumers.get("removed") or consumers.get("modified"):
        if risk not in ("breaking", "high"):
            risk = "high"
        reasons.append("consumer governance policy changed")

    acceleration = diff.get("details", {}).get("acceleration", {})
    performance = diff.get("details", {}).get("performance", {})
    if (acceleration.get("modified") or performance.get("modified")) and risk == "low":
        risk = "medium"
        reasons.append("performance or acceleration policy changed")

    if not reasons:
        reasons.append("non-breaking semantic metadata changed")

    return {
        "risk": risk,
        "approval_required": risk in {"medium", "high", "breaking"},
        "reasons": reasons,
        "changed_sections": diff.get("changed_sections", []),
        "impacted_artifacts": diff.get("impacted_artifacts", []),
    }


def main() -> int:
    args = parse_args()
    diff = json.loads(args.diff.read_text(encoding="utf-8"))
    result = classify(diff)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
