"""Truthful local CoCo benchmark/certification status for operator surfaces."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


COCO_TRACK = "COCO_PARITY_CERTIFICATION"
IMPLEMENTED_STATES = {"implemented", "implemented_on_branch", "superior"}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"certification document must be an object: {path}")
    return value


def coco_certification_status(root: str | Path) -> dict[str, Any]:
    """Return benchmark state without inferring live or superiority certification."""

    repo = Path(root).expanduser().resolve()
    ledger_path = repo / "specs" / "ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json"
    scenarios_path = repo / "specs" / "COCO_GOLDEN_SCENARIOS.json"
    report_path = repo / "reports" / "certification" / "coco_certification_report.json"

    ledger = _load(ledger_path)
    scenario_spec = _load(scenarios_path)
    report = _load(report_path)
    capabilities = list(ledger.get("capabilities") or [])
    coco = [item for item in capabilities if item.get("certification_track") == COCO_TRACK]
    extensions = [item for item in capabilities if item.get("certification_track") != COCO_TRACK]

    unresolved = [
        {
            "id": str(item.get("id") or ""),
            "current": str(item.get("ade_current") or "unknown"),
            "phase": str(item.get("phase") or ""),
            "reference": str(item.get("reference") or ""),
            "acceptance": str(item.get("acceptance") or ""),
            "known_limitation": item.get("known_limitation"),
        }
        for item in coco
        if item.get("ade_current") not in IMPLEMENTED_STATES
    ]
    unresolved.sort(key=lambda item: (item["phase"], item["id"]))

    by_current = Counter(str(item.get("ade_current") or "unknown") for item in capabilities)
    coco_by_current = Counter(str(item.get("ade_current") or "unknown") for item in coco)
    by_phase = Counter(str(item.get("phase") or "unknown") for item in coco)
    scenarios = list(scenario_spec.get("scenarios") or [])

    exact_head_evidence = None
    if report:
        exact_head_evidence = {
            "head_sha": report.get("head_sha"),
            "local_ci_certified": bool(report.get("local_ci_certified", False)),
            "coco_parity_complete": bool(report.get("coco_parity_complete", False)),
            "golden_scenarios": report.get("golden_scenarios") or {},
            "certification_fingerprint": report.get("certification_fingerprint"),
        }

    payload = {
        "status": "PASS",
        "benchmark": ledger.get("benchmark") or "CoCo public capability reference",
        "target_matrix_version": (ledger.get("target_matrix") or {}).get("version"),
        "capability_count": len(capabilities),
        "coco_capability_count": len(coco),
        "extension_capability_count": len(extensions),
        "implemented_coco_count": len(coco) - len(unresolved),
        "unresolved_coco_count": len(unresolved),
        "by_current": dict(sorted(by_current.items())),
        "coco_by_current": dict(sorted(coco_by_current.items())),
        "coco_by_phase": dict(sorted(by_phase.items())),
        "unresolved_coco_capabilities": unresolved,
        "golden_scenario_definitions": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "expected": item.get("expected"),
                "external_required": bool(item.get("external_required", False)),
                "certification_track": item.get("certification_track") or COCO_TRACK,
            }
            for item in scenarios
        ],
        "exact_head_evidence": exact_head_evidence,
        "claims": {
            "implementation_parity_ready": not unresolved,
            "exact_head_ci_certified": bool(
                exact_head_evidence and exact_head_evidence.get("local_ci_certified")
            ),
            "live_external_certified": False,
            "superiority_certified": False,
        },
        "truthfulness": {
            "extensions_do_not_gate_coco_parity": True,
            "live_external_not_inferred_from_local_tests": True,
            "superiority_not_inferred_from_implementation": True,
            "missing_ci_report_never_treated_as_green": True,
        },
        "source_files": {
            "ledger": ledger_path.relative_to(repo).as_posix(),
            "golden_scenarios": scenarios_path.relative_to(repo).as_posix(),
            "exact_head_report": (
                report_path.relative_to(repo).as_posix() if report_path.is_file() else None
            ),
        },
    }
    payload["status_fingerprint"] = _digest(payload)
    return payload
