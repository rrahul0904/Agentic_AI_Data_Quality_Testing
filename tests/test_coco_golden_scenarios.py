from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs" / "COCO_GOLDEN_SCENARIOS.json"
LEDGER = ROOT / "specs" / "ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json"


def _spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_exactly_eight_unique_golden_scenarios_are_defined():
    scenarios = _spec()["scenarios"]
    ids = [item["id"] for item in scenarios]

    assert len(scenarios) == 8
    assert len(set(ids)) == 8
    assert ids == [
        "GS01_coding_workspace",
        "GS02_session_context_rules",
        "GS03_agents_and_hosted_isolation",
        "GS04_operator_ide_apps",
        "GS05_governed_permissions",
        "GS06_agentic_ml",
        "GS07_evidence_recovery",
        "GS08_extension_preservation",
    ]


def test_golden_scenarios_use_argument_vectors_not_shell_strings():
    for scenario in _spec()["scenarios"]:
        command = scenario["command"]
        assert isinstance(command, list)
        assert command[:3] == ["python", "-m", "pytest"]
        assert all(isinstance(item, str) for item in command)
        assert scenario["expected"] == "PASS"


def test_every_referenced_pytest_file_exists():
    missing = []
    for scenario in _spec()["scenarios"]:
        for item in scenario["command"]:
            if item.startswith("tests/") and not (ROOT / item).is_file():
                missing.append((scenario["id"], item))

    assert missing == []


def test_every_golden_capability_exists_in_canonical_ledger():
    known = {item["id"] for item in _ledger()["capabilities"]}
    missing = []
    for scenario in _spec()["scenarios"]:
        for capability in scenario.get("capabilities", []):
            if capability not in known:
                missing.append((scenario["id"], capability))

    assert missing == []


def test_extension_preservation_is_not_a_coco_parity_scenario():
    scenarios = {item["id"]: item for item in _spec()["scenarios"]}
    extension = scenarios["GS08_extension_preservation"]

    assert extension["certification_track"] == "ADE_EXTENSION_ASSURANCE"
    assert extension["external_required"] is False

    extension_ids = set(extension["capabilities"])
    ledger = {item["id"]: item for item in _ledger()["capabilities"]}
    assert extension_ids
    for capability_id in extension_ids:
        assert ledger[capability_id]["certification_track"] != "COCO_PARITY_CERTIFICATION"


def test_coco_golden_scenarios_do_not_claim_live_external_certification():
    for scenario in _spec()["scenarios"]:
        assert scenario["external_required"] is False


def test_target_matrix_new_first_class_capabilities_remain_release_tracked():
    ledger = _ledger()
    target = ledger["target_matrix"]
    required = set(target["required_capabilities"])
    capability_ids = {item["id"] for item in ledger["capabilities"]}

    assert target["version"] == "2026-09-coco-parity-expanded"
    assert required <= capability_ids
    assert {
        "tools.python_repl",
        "sessions.checkpoints",
        "agents.teams",
        "rules.instructions",
        "context.pin_exclude",
        "hosted.workspace_isolation",
        "surfaces.operator_console",
        "ide.vscode",
        "apps.generic_workflow",
        "governance.permissions_admin",
        "ml.agentic_workflow",
    } <= required
