from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    return load_module(
        "rga_agent_smoke_test",
        ROOT / "scripts" / "rga_testbed" / "run_agent_smoke.py",
    )


def test_agent_smoke_defaults_to_governed_rga_agent():
    module = _module()
    contract = {
        "database": "RGA_SYNTHETIC_TESTBED",
        "verified_queries": [{"question": "What is the ceded loss ratio?"}],
    }
    assert module.default_agent(contract) == "RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT"
    assert module.questions(contract, None) == ["What is the ceded loss ratio?"]


def test_agent_request_is_non_streaming_and_user_scoped():
    module = _module()
    body = module.request_body("What is ceded premium?")
    assert body["background"] is False
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"][0]["text"] == "What is ceded premium?"


def test_agent_evidence_keeps_final_text_and_tool_but_not_thinking():
    module = _module()
    response = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": {"text": "private reasoning"}},
            {
                "type": "tool_use",
                "tool_use": {
                    "name": "Reinsurance_Analyst",
                    "tool_use_id": "tool-1",
                },
            },
            {"type": "text", "text": "Ceded premium was 100."},
        ],
        "warnings": [],
        "metadata": {"run_id": "run-1"},
    }
    evidence = module.extract_evidence(response)
    assert evidence["role"] == "assistant"
    assert evidence["text"] == "Ceded premium was 100."
    assert evidence["tool_names"] == ["Reinsurance_Analyst"]
    assert evidence["run_id"] == "run-1"
    assert "private reasoning" not in str(evidence)


def test_agent_evidence_requires_governed_tool_and_no_warnings():
    module = _module()
    good = {
        "role": "assistant",
        "text": "answer",
        "tool_names": ["Reinsurance_Analyst"],
        "warnings": [],
    }
    status, errors = module.assess_evidence(good)
    assert status == "PASS"
    assert errors == []

    bad = {
        "role": "assistant",
        "text": "answer",
        "tool_names": [],
        "warnings": [{"code": "399569", "message": "tool unavailable"}],
    }
    status, errors = module.assess_evidence(bad)
    assert status == "FAIL"
    assert any("Reinsurance_Analyst" in error for error in errors)
    assert any("warnings" in error for error in errors)


def test_agent_smoke_dry_run_lists_acceptance_contract():
    module = _module()
    payload = module.dry_run_payload(
        "RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT",
        ["q1", "q2"],
    )
    assert payload["status"] == "DRY_RUN"
    assert payload["task_count"] == 2
    assert any("governed tool use" in item for item in payload["acceptance"])
    assert any("reasoning/thinking content is not persisted" in item for item in payload["acceptance"])
