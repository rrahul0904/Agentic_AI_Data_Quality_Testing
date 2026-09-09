from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_LEDGER = Path("specs/ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json")
ALLOWED_PHASES = {"P0", "P1", "P2"}
ALLOWED_CURRENT = {"implemented", "implemented_on_branch", "partial", "gap", "superior"}
ALLOWED_CLASSIFICATIONS = {"COCO_CORE", "COCO_WORKFLOW", "ADE_EXTENSION"}
ALLOWED_TRACKS = {"COCO_PARITY_CERTIFICATION", "SNOWFLAKE_EXTENSION_CERTIFICATION"}


def load_ledger(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("ledger root must be an object")
    return payload


def _in_scope(item: dict[str, Any], scope: str) -> bool:
    classification = item.get("classification")
    if scope == "all":
        return True
    if scope == "coco":
        return classification in {"COCO_CORE", "COCO_WORKFLOW"}
    if scope == "extensions":
        return classification == "ADE_EXTENSION"
    raise ValueError(f"unknown scope: {scope}")


def _local_certification(item: dict[str, Any]) -> str:
    certification = item.get("certification")
    if isinstance(certification, dict):
        return str(certification.get("local") or "NOT_CERTIFIED")
    return "NOT_CERTIFIED"


def _live_certification(item: dict[str, Any]) -> str:
    certification = item.get("certification")
    if isinstance(certification, dict):
        return str(certification.get("live") or "NOT_RUN_EXTERNAL")
    if item.get("classification") == "ADE_EXTENSION":
        return "NOT_RUN_EXTERNAL"
    return "NOT_REQUIRED"


def validate(
    payload: dict[str, Any],
    *,
    require_target: bool = False,
    require_coco_parity: bool = False,
    scope: str = "all",
) -> dict[str, Any]:
    errors: list[str] = []
    parity_blockers: list[str] = []
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
    by_classification = {classification: 0 for classification in sorted(ALLOWED_CLASSIFICATIONS)}
    scoped_current: dict[str, int] = {}
    scoped_live: dict[str, int] = {}
    scoped_count = 0

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

        classification = item.get("classification")
        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(f"{prefix}.classification must be one of {sorted(ALLOWED_CLASSIFICATIONS)}")
        else:
            by_classification[classification] += 1

        release_blocking = item.get("release_blocking")
        if not isinstance(release_blocking, bool):
            errors.append(f"{prefix}.release_blocking must be boolean")
        elif classification == "ADE_EXTENSION" and release_blocking:
            errors.append(f"{prefix} ADE_EXTENSION must not block CoCo parity")

        track = item.get("certification_track")
        if track not in ALLOWED_TRACKS:
            errors.append(f"{prefix}.certification_track must be one of {sorted(ALLOWED_TRACKS)}")
        elif classification == "ADE_EXTENSION" and track != "SNOWFLAKE_EXTENSION_CERTIFICATION":
            errors.append(f"{prefix} ADE_EXTENSION must use SNOWFLAKE_EXTENSION_CERTIFICATION")
        elif classification in {"COCO_CORE", "COCO_WORKFLOW"} and track != "COCO_PARITY_CERTIFICATION":
            errors.append(f"{prefix} CoCo capability must use COCO_PARITY_CERTIFICATION")

        if item.get("target_score") != 2:
            errors.append(f"{prefix}.target_score must remain 2")
        advantages = item.get("superiority_advantages")
        if not isinstance(advantages, list) or len(advantages) < 2:
            errors.append(f"{prefix}.superiority_advantages must contain at least two testable advantages")
        if not str(item.get("acceptance") or "").strip():
            errors.append(f"{prefix}.acceptance is required")

        if require_target and current != "superior":
            errors.append(f"{capability_id or prefix} has not reached SUPERIOR")

        if _in_scope(item, scope):
            scoped_count += 1
            if current in ALLOWED_CURRENT:
                scoped_current[current] = scoped_current.get(current, 0) + 1
            live = _live_certification(item)
            scoped_live[live] = scoped_live.get(live, 0) + 1

        if require_coco_parity and bool(release_blocking):
            if current in {"gap", "partial"}:
                parity_blockers.append(f"{capability_id}: implementation status is {current}")
            elif current in {"implemented_on_branch", "superior"} and _local_certification(item) != "PASS":
                parity_blockers.append(f"{capability_id}: deterministic local certification is not PASS")
            if item.get("live_required_for_coco") is True and _live_certification(item) != "PASS":
                parity_blockers.append(f"{capability_id}: required live CoCo certification is not PASS")

    duplicates = sorted({item for item in ids if item and ids.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate capability ids: {', '.join(duplicates)}")

    if require_coco_parity:
        errors.extend(parity_blockers)

    return {
        "status": "PASS" if not errors else "FAIL",
        "capability_count": len(entries),
        "scoped_capability_count": scoped_count,
        "scope": scope,
        "source_count": len(sources or []),
        "by_phase": by_phase,
        "by_current": dict(sorted(by_current.items())),
        "by_classification": dict(sorted(by_classification.items())),
        "scoped_by_current": dict(sorted(scoped_current.items())),
        "scoped_by_live_certification": dict(sorted(scoped_live.items())),
        "release_blockers": parity_blockers,
        "target_score": 2,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--require-target", action="store_true")
    parser.add_argument("--require-coco-parity", action="store_true")
    parser.add_argument("--scope", choices=("all", "coco", "extensions"), default="all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(
        load_ledger(args.ledger),
        require_target=args.require_target,
        require_coco_parity=args.require_coco_parity,
        scope=args.scope,
    )
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
