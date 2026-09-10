#!/usr/bin/env python3
"""Promote CoCo ledger declarations only from exact-head passing golden evidence.

This script deliberately never promotes ADE extensions, never sets SUPERIOR, and
fails closed when golden evidence is stale or incomplete.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "specs" / "ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json"
DEFAULT_GOLDEN = ROOT / "reports" / "certification" / "coco_golden_scenarios.json"
COCO_TRACK = "COCO_PARITY_CERTIFICATION"
IMPLEMENTED_STATES = {"implemented", "implemented_on_branch", "superior"}


def git_head() -> str | None:
    explicit = os.getenv("GITHUB_HEAD_SHA") or os.getenv("GITHUB_SHA")
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def passing_coco_capabilities(golden: dict[str, Any]) -> set[str]:
    certified: set[str] = set()
    for scenario in golden.get("results") or []:
        if scenario.get("status") != "PASS":
            continue
        if scenario.get("certification_track", COCO_TRACK) != COCO_TRACK:
            continue
        certified.update(str(item) for item in scenario.get("capabilities") or [])
    return certified


def promote(ledger: dict[str, Any], golden: dict[str, Any], *, head: str | None) -> tuple[dict[str, Any], list[str]]:
    if not (
        golden.get("status") == "PASS"
        and golden.get("scenario_count") == 8
        and golden.get("passed") == 8
        and golden.get("failed") == 0
    ):
        raise ValueError("refusing ledger promotion: all eight golden scenarios are not PASS")

    golden_head = golden.get("head_sha")
    if not head or not golden_head or head != golden_head:
        raise ValueError(
            f"refusing ledger promotion: exact-head mismatch (source={head!r}, golden={golden_head!r})"
        )

    certified = passing_coco_capabilities(golden)
    promoted: list[str] = []
    capabilities = ledger.get("capabilities") or []

    for item in capabilities:
        if item.get("certification_track") != COCO_TRACK:
            continue
        capability_id = str(item.get("id") or "")
        if item.get("ade_current") in IMPLEMENTED_STATES:
            continue
        if capability_id not in certified:
            continue
        item["ade_current"] = "implemented_on_branch"
        limitation = item.get("known_limitation")
        if isinstance(limitation, str) and "awaits exact-head deterministic certification" in limitation.casefold():
            item["known_limitation"] = None
        promoted.append(capability_id)

    unresolved = [
        str(item.get("id") or "")
        for item in capabilities
        if item.get("certification_track") == COCO_TRACK
        and item.get("ade_current") not in IMPLEMENTED_STATES
    ]
    if unresolved:
        raise ValueError(
            "refusing partial ledger synchronization; unresolved CoCo capabilities remain: "
            + ", ".join(sorted(unresolved))
        )

    return ledger, promoted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--check", action="store_true", help="validate promotion without writing")
    args = parser.parse_args()

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    updated, promoted = promote(ledger, golden, head=git_head())

    if not args.check:
        args.ledger.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "head_sha": git_head(),
        "promoted_count": len(promoted),
        "promoted": sorted(promoted),
        "wrote_ledger": not args.check,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
