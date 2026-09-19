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


def test_agent_smoke_defaults_to_governed_rga_agent_and_verified_query_ids():
    module = _module()
    contract = {
        "database": "RGA_SYNTHETIC_TESTBED",
        "verified_queries": [{"id": "loss_ratio", "question": "What is the ceded loss ratio?"}],
    }
    assert module.default_agent(contract) == "RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT"
    assert module.tasks(contract, None) == [
        {"id": "loss_ratio", "question": "What is the ceded loss ratio?"}
    ]
    assert module.questions(contract, None) == ["What is the ceded loss ratio?"]


def test_agent_request_is_non_streaming_and_user_scoped():
    module = _module()
    body = module.request_body("What is ceded premium?")
    assert body["background"] is False
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"][0]["text"] == "What is ceded premium?"


def test_agent_evidence_extracts_current_system_execute_sql_result_without_thinking():
    module = _module()
    response = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": {"text": "private reasoning"}},
            {
                "type": "tool_use",
                "tool_use": {
                    "name": "system_execute_sql",
                    "type": "system_execute_sql",
                    "tool_use_id": "tool-1",
                    "input": {"sql": "select 100 as total_ceded_premium"},
                },
            },
            {
                "type": "tool_result",
                "tool_result": {
                    "name": "system_execute_sql",
                    "type": "system_execute_sql",
                    "status": "success",
                    "tool_use_id": "tool-1",
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "query_id": "qid-1",
                                "sql": "select 100 as total_ceded_premium",
                                "result_set": {
                                    "resultSetMetaData": {
                                        "rowType": [{"name": "TOTAL_CEDED_PREMIUM"}],
                                        "numRows": 1,
                                    },
                                    "data": [["100"]],
                                },
                            },
                        }
                    ],
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
    assert evidence["tool_names"] == ["system_execute_sql"]
    assert evidence["tool_types"] == ["system_execute_sql"]
    assert evidence["run_id"] == "run-1"
    assert len(evidence["analytical_executions"]) == 1
    execution = evidence["analytical_executions"][0]
    assert execution["query_id"] == "qid-1"
    assert execution["result_signature"]["row_count"] == 1
    assert execution["result_signature"]["value_sha256"]
    assert "private reasoning" not in str(evidence)


def test_agent_evidence_requires_successful_analytical_result_and_no_warnings():
    module = _module()
    good = {
        "role": "assistant",
        "text": "answer",
        "analytical_executions": [
            {
                "name": "system_execute_sql",
                "type": "system_execute_sql",
                "status": "success",
                "result_signature": {"result_sha256": "strict", "value_sha256": "values"},
            }
        ],
        "warnings": [],
    }
    status, errors = module.assess_evidence(good)
    assert status == "PASS"
    assert errors == []

    bad = {
        "role": "assistant",
        "text": "answer",
        "analytical_executions": [],
        "warnings": [{"code": "399569", "message": "tool unavailable"}],
    }
    status, errors = module.assess_evidence(bad)
    assert status == "FAIL"
    assert any("analytical SQL result set" in error for error in errors)
    assert any("warnings" in error for error in errors)


def test_agent_smoke_dry_run_lists_current_analytical_acceptance_contract():
    module = _module()
    payload = module.dry_run_payload(
        "RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT",
        [
            {"id": "q1", "question": "question one"},
            {"id": "q2", "question": "question two"},
        ],
    )
    assert payload["status"] == "DRY_RUN"
    assert payload["task_count"] == 2
    assert any("system_execute_sql" in item for item in payload["acceptance"])
    assert any("canonical signature" in item for item in payload["acceptance"])
    assert any("reasoning/thinking content is not persisted" in item for item in payload["acceptance"])
