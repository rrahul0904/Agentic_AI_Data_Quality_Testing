from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

from agentic_data_platform import semantic_platform_cli_ext as ext

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    generator = load_module(
        "semantic_platform_excel_ext_parity",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )
    workspace = tmp_path / "workspace"
    generator.generate(
        workspace / "release" / "parity",
        "RGA_SYNTHETIC_TESTBED",
    )
    ai_dir = workspace / "release" / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    (ai_dir / "mcp_spec.yml").write_text(
        yaml.safe_dump(
            {
                "tools": [
                    {
                        "name": "reinsurance_analyst",
                        "type": "CORTEX_AGENT_RUN",
                        "identifier": "RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return workspace


def test_excel_extension_dry_run_uses_workspace_parity_manifest(tmp_path: Path):
    workspace = _workspace(tmp_path)
    result = ext.capture_excel_evidence(
        workspace,
        evidence_dir=tmp_path / "evidence",
        security_context="ROLE_ANALYST",
        dry_run=True,
    )
    assert result["status"] == "DRY_RUN"
    assert result["case_count"] >= 3
    assert all(item["mdx_exists"] for item in result["cases"])
    assert result["consumer_evidence"]["required_consumers"] == [
        "snowflake_semantic_view",
        "cortex_agent_mcp",
        "power_bi",
        "excel",
    ]


def test_capture_all_evidence_dry_run_plans_all_four_consumers(tmp_path: Path):
    workspace = _workspace(tmp_path)
    result = ext.capture_all_evidence(
        workspace,
        evidence_dir=tmp_path / "evidence",
        security_context="ROLE_ANALYST",
        dry_run=True,
    )
    assert result["status"] == "DRY_RUN"
    assert result["planned_consumers"] == [
        "snowflake_semantic_view",
        "cortex_agent_mcp",
        "power_bi",
        "excel",
    ]
    assert result["planned_runtime_surfaces"] == []
    assert result["governed"]["status"] == "DRY_RUN"
    assert result["governed"]["power_bi"]["status"] == "DRY_RUN"
    assert result["excel"]["status"] == "DRY_RUN"
    assert result["managed_mcp"]["status"] == "NOT_REQUESTED"


def test_capture_all_evidence_can_plan_managed_mcp_runtime(tmp_path: Path):
    workspace = _workspace(tmp_path)
    result = ext.capture_all_evidence(
        workspace,
        evidence_dir=tmp_path / "evidence",
        security_context="ROLE_ANALYST",
        run_mcp_smoke=True,
        mcp_endpoint=(
            "https://acct.snowflakecomputing.com/api/v2/databases/"
            "RGA_SYNTHETIC_TESTBED/schemas/AI/mcp-servers/RGA_REINSURANCE_MCP"
        ),
        dry_run=True,
    )
    assert result["status"] == "DRY_RUN"
    assert result["planned_consumers"] == [
        "snowflake_semantic_view",
        "cortex_agent_mcp",
        "power_bi",
        "excel",
    ]
    assert result["planned_runtime_surfaces"] == [
        "snowflake_managed_mcp_remote_client"
    ]
    assert result["managed_mcp"]["status"] == "DRY_RUN"
    assert result["managed_mcp"]["expected_tool"] == "reinsurance_analyst"


def test_capture_all_evidence_fails_when_requested_mcp_runtime_fails(
    tmp_path: Path,
    monkeypatch,
):
    workspace = _workspace(tmp_path)
    evidence_dir = tmp_path / "evidence"

    monkeypatch.setattr(
        ext.base,
        "capture_governed_evidence",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        ext,
        "capture_excel_evidence",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        ext,
        "mcp_remote_smoke",
        lambda *args, **kwargs: {"status": "FAIL"},
    )
    monkeypatch.setattr(
        ext.base,
        "consumer_parity_plan",
        lambda *args, **kwargs: {
            "expected_evidence_count": 12,
            "captured_evidence_count": 12,
            "missing_evidence_count": 0,
            "pending_evidence_count": 0,
            "invalid_evidence_count": 0,
        },
    )
    monkeypatch.setattr(
        ext.base,
        "certify_consumers",
        lambda *args, **kwargs: {"status": "PASS"},
    )

    result = ext.capture_all_evidence(
        workspace,
        evidence_dir=evidence_dir,
        security_context="ROLE_ANALYST",
        run_mcp_smoke=True,
        confirm=True,
    )
    assert result["status"] == "FAIL"
    assert result["managed_mcp"]["status"] == "FAIL"
    assert result["runtime_surfaces_remaining"] == [
        "snowflake_managed_mcp_remote_client"
    ]


def test_mcp_extension_derives_governed_tool_and_verified_question(tmp_path: Path):
    workspace = _workspace(tmp_path)
    result = ext.mcp_remote_smoke(
        workspace,
        endpoint=(
            "https://acct.snowflakecomputing.com/api/v2/databases/"
            "RGA_SYNTHETIC_TESTBED/schemas/AI/mcp-servers/RGA_REINSURANCE_MCP"
        ),
        dry_run=True,
    )
    parity = json.loads(
        (workspace / "release" / "parity" / "parity_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "DRY_RUN"
    assert result["expected_tool"] == "reinsurance_analyst"
    assert result["question_sha256"]
    assert result["source_mcp_spec"].endswith("mcp_spec.yml")
    assert result["source_parity_manifest"].endswith("parity_manifest.json")
    expected_question = parity["cases"][0]["business_question"]
    smoke_module = load_module(
        "semantic_platform_mcp_hash_test",
        ROOT / "scripts" / "rga_testbed" / "smoke_snowflake_mcp.py",
    )
    assert result["question_sha256"] == smoke_module.hashlib.sha256(
        expected_question.encode()
    ).hexdigest()


def test_mcp_extension_requires_workspace_governed_tool(tmp_path: Path):
    workspace = _workspace(tmp_path)
    (workspace / "release" / "ai" / "mcp_spec.yml").write_text(
        "tools: []\n",
        encoding="utf-8",
    )
    try:
        ext.mcp_remote_smoke(
            workspace,
            endpoint="https://acct.example/mcp",
            dry_run=True,
        )
    except ValueError as exc:
        assert "does not expose a named governed tool" in str(exc)
    else:
        raise AssertionError("MCP smoke must require a governed tool in the release")


def test_extension_delegates_existing_commands_to_certified_base(monkeypatch):
    monkeypatch.setattr(ext.base, "main", lambda: 17)
    monkeypatch.setattr(sys, "argv", ["semantic-platform", "about"])
    assert ext.main() == 17
