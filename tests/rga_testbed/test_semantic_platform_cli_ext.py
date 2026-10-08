from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
    assert result["governed"]["status"] == "DRY_RUN"
    assert result["governed"]["power_bi"]["status"] == "DRY_RUN"
    assert result["excel"]["status"] == "DRY_RUN"


def test_extension_delegates_existing_commands_to_certified_base(monkeypatch):
    monkeypatch.setattr(ext.base, "main", lambda: 17)
    monkeypatch.setattr(sys, "argv", ["semantic-platform", "about"])
    assert ext.main() == 17
