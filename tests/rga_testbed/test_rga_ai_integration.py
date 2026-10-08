from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_agent_uses_same_governed_semantic_view(tmp_path: Path):
    module = load_module("rga_ai", ROOT / "scripts" / "rga_testbed" / "generate_ai_integration.py")
    spec = module.build_agent_spec("RGA_SYNTHETIC_TESTBED")
    assert spec["tools"][0]["tool_spec"]["type"] == "cortex_analyst_text_to_sql"
    assert spec["tool_resources"]["Reinsurance_Analyst"]["semantic_view"] == (
        "RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE"
    )
    assert spec["orchestration"]["capabilities"]["analytical_search"] is True
    files = module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    assert len(files) == 4
    parsed = yaml.safe_load((tmp_path / "agent_spec.yml").read_text(encoding="utf-8"))
    assert parsed["tool_resources"] == spec["tool_resources"]


def test_mcp_exposes_agent_not_unrestricted_sql(tmp_path: Path):
    module = load_module("rga_ai_mcp", ROOT / "scripts" / "rga_testbed" / "generate_ai_integration.py")
    spec = module.build_mcp_spec("RGA_SYNTHETIC_TESTBED")
    assert len(spec["tools"]) == 1
    tool = spec["tools"][0]
    assert tool["type"] == "CORTEX_AGENT_RUN"
    assert tool["identifier"] == "RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT"
    assert "SYSTEM_EXECUTE_SQL" not in yaml.safe_dump(spec)
    module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    sql = (tmp_path / "create_mcp_server.sql").read_text(encoding="utf-8")
    assert "CREATE OR REPLACE MCP SERVER RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_MCP" in sql
    assert "CORTEX_AGENT_RUN" in sql


def test_agent_sql_uses_create_agent_specification(tmp_path: Path):
    module = load_module("rga_ai_sql", ROOT / "scripts" / "rga_testbed" / "generate_ai_integration.py")
    module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    sql = (tmp_path / "create_agent.sql").read_text(encoding="utf-8")
    assert "CREATE OR REPLACE AGENT RGA_SYNTHETIC_TESTBED.AI.RGA_REINSURANCE_AGENT" in sql
    assert "FROM SPECIFICATION" in sql
    assert "cortex_analyst_text_to_sql" in sql
    assert "RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE" in sql
