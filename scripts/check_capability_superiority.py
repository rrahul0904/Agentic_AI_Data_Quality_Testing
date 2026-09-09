#!/usr/bin/env python3
"""Validate the internal reference-capability superiority ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_LEDGER = Path("specs/ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json")
ALLOWED_PHASES = {"P0", "P1", "P2"}
ALLOWED_CURRENT = {"implemented", "implemented_on_branch", "partial", "gap", "superior"}


def load_ledger(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("ledger root must be an object")
    return payload


def validate(payload: dict[str, Any], *, require_target: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    entries = payload.get("capabilities")
    sources = payload.get("sources")

    if not isinstance(sources, list) or not sources:
        errors.append("sources must contain at least one public reference URL")
    elif any(not str(source).startswith("https://docs.snowflake.com/") for source in sources):
        errors.append("all benchmark sources must be Snowflake documentation URLs")

    if not isinstance(entries, list) or not entries:
        errors.append("capabilities must be a non-empty list")
        entries = []

    ids: list[str] = []
    by_phase = {phase: 0 for phase in sorted(ALLOWED_PHASES)}
    by_current: dict[str, int] = {}

    for index, item in enumerate(entries):
        prefix = f"capabilities[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        capability_id = str(item.get("id") or "")
        ids.append(capability_id)
        if not capability_id or "." not in capability_id:
            errors.append(f"{prefix}.id must be a stable dotted identifier")
        if not str(item.get("reference") or "").strip():
            errors.append(f"{prefix}.reference is required")
        phase = item.get("phase")
        if phase not in ALLOWED_PHASES:
            errors.append(f"{prefix}.phase must be one of {sorted(ALLOWED_PHASES)}")
        else:
            by_phase[phase] += 1
        current = item.get("ade_current")
        if current not in ALLOWED_CURRENT:
            errors.append(f"{prefix}.ade_current must be one of {sorted(ALLOWED_CURRENT)}")
        else:
            by_current[current] = by_current.get(current, 0) + 1
        if item.get("target_score") != 2:
            errors.append(f"{prefix}.target_score must remain 2")
        advantages = item.get("superiority_advantages")
        if not isinstance(advantages, list) or len(advantages) < 2:
            errors.append(f"{prefix}.superiority_advantages must contain at least two testable advantages")
        if not str(item.get("acceptance") or "").strip():
            errors.append(f"{prefix}.acceptance is required")
        if require_target and current != "superior":
            errors.append(f"{capability_id or prefix} has not reached SUPERIOR")

    duplicates = sorted({item for item in ids if item and ids.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate capability ids: {', '.join(duplicates)}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "capability_count": len(entries),
        "source_count": len(sources or []),
        "by_phase": by_phase,
        "by_current": dict(sorted(by_current.items())),
        "target_score": 2,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--require-target", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(load_ledger(args.ledger), require_target=args.require_target)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
