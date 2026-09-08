from __future__ import annotations

from pathlib import Path

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.tools.builtin import build_tool_registry


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "hospitality-snowflake-data-platform"


def test_supervisor_reuses_only_static_repository_reads(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        PROJECT,
    )
    service.investigate("watermark_defect")
    first = service.cache_metrics()
    assert first["entries"] > 0
    assert first["misses"] > 0

    service.investigate("airflow_green_data_bad")
    second = service.cache_metrics()
    assert second["entries"] >= first["entries"]
    assert second["hits"] > first["hits"]


def test_cached_tool_results_are_defensively_copied(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        PROJECT,
    )
    first = service._invoke(
        service.metadata.role,
        "airflow_inventory",
        {"project": str(PROJECT)},
    )
    first["dag_count"] = -1
    second = service._invoke(
        service.metadata.role,
        "airflow_inventory",
        {"project": str(PROJECT)},
    )
    assert second["dag_count"] >= 57
