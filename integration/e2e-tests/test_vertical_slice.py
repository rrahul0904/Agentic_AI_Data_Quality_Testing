from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "hospitality-snowflake-data-platform"))
sys.path.insert(0, str(ROOT / "hospitality-snowflake-data-platform" / "airflow"))

from agentic_data_platform.models import ActorMode, Environment, Risk, ToolRequest  # noqa: E402
from agentic_data_platform.platform.discovery import PlatformDiscovery  # noqa: E402
from agentic_data_platform.platform.graph import PlatformAssetGraph  # noqa: E402
from agentic_data_platform.quality.reconciliation import reconcile_row_count  # noqa: E402
from agentic_data_platform.quality.store import QualityResult, SQLiteQualityStore  # noqa: E402
from agentic_data_platform.tools.builtin import build_tool_registry  # noqa: E402
from agentic_data_platform.tools.registry import ToolInvocation  # noqa: E402


HOSPITALITY = ROOT / "hospitality-snowflake-data-platform"


def test_platform_discovery():
    value = PlatformDiscovery(HOSPITALITY).discover()
    assert value["sources"]["oracle_tables"] == 144
    assert value["sources"]["postgres_tables"] == 157
    assert value["sources"]["file_feeds"] == 18


def test_dbt_manifest_and_lineage():
    registry = build_tool_registry()
    result = registry.invoke(ToolInvocation(ToolRequest("dbt_lineage", "read", Environment.DEV, Risk.READ_ONLY, args={"project": str(HOSPITALITY), "node": "fact_reservation"}), "e2e"))
    assert any(node["name"] == "int_reservation_lifecycle" for node in result["upstream"])


def test_cross_system_lineage_and_impact():
    graph = PlatformAssetGraph.build(HOSPITALITY)
    lineage = graph.lineage("fact_reservation")
    assert any(item["name"] == "oracle.RESERVATION" for item in lineage["upstream"])
    assert graph.impact("stg_oracle_reservation")["affected_marts"]


def test_reconciliation_and_quality_failure_and_pass(tmp_path):
    assert reconcile_row_count(10, 10)["status"] == "PASS"
    assert reconcile_row_count(10, 9)["status"] == "FAIL"
    store = SQLiteQualityStore(tmp_path / "quality.sqlite")
    store.initialize()
    run = store.start_run("reservation-fixture")
    store.save_result(QualityResult("duplicate_reservation", run, "local", "RAW", "RESERVATION", "duplicate_key", "ERROR", "FAIL", 1, 0))
    store.complete_run(run, "FAIL")
    assert store.get_run(run)["status"] == "FAIL"


def test_analyst_cannot_invoke_builder_migration():
    registry = build_tool_registry()
    definition = registry.describe("migration_convert_model")
    request = ToolRequest(definition.name, "convert", Environment.DEV, definition.risk, args={"sql": "select 1"})
    with pytest.raises(PermissionError):
        registry.invoke(ToolInvocation(request, "e2e-analyst", actor_mode=ActorMode.ANALYST))


def test_snowflake_is_explicitly_skipped_without_credentials():
    health = PlatformDiscovery(HOSPITALITY).health()
    assert health["checks"]["snowflake_live"]["status"] in {"SKIP", "PASS"}


def test_hospitality_local_reservation_runner(tmp_path, monkeypatch):
    pytest.importorskip("airflow")
    from data_generator.relational_exports import generate_relational_exports
    from airflow.include.framework.local_runner import run_local_job

    source_root = tmp_path / "source_exports"
    generate_relational_exports("oracle", "small", source_root, seed=11, max_rows=3)
    monkeypatch.setenv("SOURCE_EXPORT_DIR", str(source_root))
    monkeypatch.setenv("LOCAL_LANDING_DIR", str(tmp_path / "landing"))
    monkeypatch.setenv("LOCAL_AUDIT_DB", str(tmp_path / "audit.sqlite"))
    result = run_local_job({"dag_id": "oracle_reservation_ingest", "source": "oracle", "entities": ["RESERVATION"], "load_strategy": "timestamp_incremental"})
    assert result["quality"]["status"] == "PASS"
    assert result["reconciliation"]["status"] == "PASS"
