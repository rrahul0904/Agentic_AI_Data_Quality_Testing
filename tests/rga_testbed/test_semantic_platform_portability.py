from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BANKING_CONTRACT = ROOT / "config" / "examples" / "banking_semantic_contract.yml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_non_rga_contract_compiles_full_governed_release_without_domain_leakage(
    tmp_path: Path,
):
    release_mod = load_module(
        "generic_semantic_release_test",
        ROOT / "scripts" / "rga_testbed" / "build_semantic_release.py",
    )
    output = tmp_path / "banking-release"
    release = release_mod.build_release(
        output,
        "BANKING_ANALYTICS",
        contract_path=BANKING_CONTRACT,
        source_sha="test-sha",
    )

    assert release["semantic_view"] == (
        "BANKING_ANALYTICS.SEMANTIC.BANKING_ACCOUNT_PERFORMANCE"
    )
    assert release["source_sha"] == "test-sha"
    assert "multi_fact" not in release["impacted_artifacts"]
    assert not (output / "multi_fact").exists()
    assert (
        output
        / "interchange"
        / "banking_account_performance.ossie.yml"
    ).exists()

    generated_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".json", ".yml", ".yaml", ".sql", ".md", ".dax"}
    ).lower()
    assert "rga_" not in generated_text
    assert "rga " not in generated_text
    assert "reinsurance" not in generated_text

    agent_sql = (output / "ai" / "create_agent.sql").read_text(encoding="utf-8")
    mcp_sql = (output / "ai" / "create_mcp_server.sql").read_text(encoding="utf-8")
    assert "BANKING_ACCOUNT_PERFORMANCE_AGENT" in agent_sql
    assert "BANKING_ACCOUNT_PERFORMANCE_MCP" in mcp_sql
    assert "Reinsurance_Analyst" not in agent_sql

    parity = json.loads(
        (output / "parity" / "parity_manifest.json").read_text(encoding="utf-8")
    )
    assert parity["name"] == (
        "banking_account_performance_cross_consumer_semantic_parity"
    )
    assert len(parity["cases"]) == 2

    microsoft = (
        output / "microsoft" / "PARITY_CHECKLIST.md"
    ).read_text(encoding="utf-8")
    assert BANKING_CONTRACT.as_posix() in microsoft
    assert "config/rga_semantic_contract.yml" not in microsoft


def test_non_rga_contract_uses_generic_domain_guidance_defaults():
    contract_mod = load_module(
        "generic_semantic_contract_test",
        ROOT / "scripts" / "rga_testbed" / "semantic_contract.py",
    )
    contract = contract_mod.load_semantic_contract(
        BANKING_CONTRACT,
        "BANKING_ANALYTICS",
    )
    names = contract_mod.ai_object_names(contract)
    guidance = contract_mod.domain_guidance(contract)

    assert names["agent_name"] == "BANKING_ACCOUNT_PERFORMANCE_AGENT"
    assert names["mcp_name"] == "BANKING_ACCOUNT_PERFORMANCE_MCP"
    assert names["tool_name"] == "Banking_Account_Performance_Analyst"
    assert "banking" in guidance["agent_response"].lower()
    assert "reinsurance" not in str(guidance).lower()


def test_rga_contract_keeps_existing_public_object_names():
    contract_mod = load_module(
        "rga_backward_compatibility_test",
        ROOT / "scripts" / "rga_testbed" / "semantic_contract.py",
    )
    contract = contract_mod.load_semantic_contract(
        ROOT / "config" / "rga_semantic_contract.yml",
        "RGA_SYNTHETIC_TESTBED",
    )
    names = contract_mod.ai_object_names(contract)

    assert names == {
        "agent_name": "RGA_REINSURANCE_AGENT",
        "mcp_name": "RGA_REINSURANCE_MCP",
        "tool_name": "Reinsurance_Analyst",
        "tool_title": "Governed RGA Reinsurance Analytics Agent",
    }


def test_banking_semantic_view_has_generic_dataset_description(tmp_path: Path):
    semantic_mod = load_module(
        "generic_semantic_view_test",
        ROOT / "scripts" / "rga_testbed" / "generate_semantic_view.py",
    )
    spec = semantic_mod.build_semantic_spec(
        "BANKING_ANALYTICS",
        BANKING_CONTRACT,
    )
    rendered = yaml.safe_dump(spec, sort_keys=False).lower()
    assert "banking" in rendered
    assert "cedant" not in rendered
    assert "treaty" not in rendered
    assert "reinsurance" not in rendered
