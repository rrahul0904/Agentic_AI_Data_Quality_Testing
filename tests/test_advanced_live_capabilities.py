from __future__ import annotations

import json
import sys

import pytest

from scripts import live_advanced_capabilities as live


def test_advanced_live_components_are_partitioned_by_external_mutation_risk():
    assert live.READ_ONLY_COMPONENTS == {"semantic", "analyst", "cortex-agent", "model-registry", "ai-workflow"}
    assert live.MUTATING_COMPONENTS == {"cortex-agent-run", "notebook", "streamlit", "app-runtime"}
    assert live.READ_ONLY_COMPONENTS.isdisjoint(live.MUTATING_COMPONENTS)
    assert live.ALL_COMPONENTS == live.READ_ONLY_COMPONENTS | live.MUTATING_COMPONENTS


def test_advanced_live_mutating_probes_fail_closed_without_explicit_approval(monkeypatch):
    monkeypatch.delenv("ADE_ADVANCED_LIVE_MUTATION_APPROVED", raising=False)
    with pytest.raises(RuntimeError, match="BLOCKED_EXTERNAL"):
        live.certify_notebook()
    with pytest.raises(RuntimeError, match="BLOCKED_EXTERNAL"):
        live.certify_cortex_agent_run()
    with pytest.raises(RuntimeError, match="BLOCKED_EXTERNAL"):
        live.certify_app("streamlit")


def test_advanced_live_app_fixture_plan_is_locally_valid(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_SNOWFLAKE_DATABASE", "HOTEL")
    monkeypatch.setenv("ADE_SNOWFLAKE_SCHEMA", "APPS")
    monkeypatch.setenv("ADE_SNOWFLAKE_WAREHOUSE", "APP_WH")
    plan = live.app_plan("app-runtime", tmp_path)
    assert plan["status"] == "PASS"
    assert plan["kind"] == "app-runtime"
    assert plan["app_name"] == "ade_live_app_runtime"
    assert "app.yml" in plan["files"]


def test_advanced_live_main_records_blocked_external_instead_of_false_pass(monkeypatch, tmp_path):
    for name in ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    output = tmp_path / "advanced-live.json"
    monkeypatch.setattr(sys, "argv", [
        "live_advanced_capabilities.py",
        "--components", "semantic",
        "--output", str(output),
    ])

    code = live.main()

    assert code == 1
    report = json.loads(output.read_text())
    assert report["status"] == "FAIL"
    assert report["components"]["semantic"]["status"] == "BLOCKED_EXTERNAL"
