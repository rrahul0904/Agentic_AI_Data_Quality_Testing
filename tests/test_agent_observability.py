from __future__ import annotations

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.tools.builtin import build_tool_registry


def test_agent_results_expose_observability_and_correlation(tmp_path):
    service = SupervisorAgent(
        build_tool_registry(),
        InvestigationStore(tmp_path / "investigations.db"),
        tmp_path / "project",
    )
    report = service.investigate("watermark_defect")
    public = service.public_report(report.incident_id)

    specialists = [item for item in public["agent_results"] if item["role"] != "supervisor"]
    assert specialists
    for result in specialists:
        telemetry = result["telemetry"]
        assert telemetry["provider"] == "deterministic"
        assert telemetry["model"] == "domain-service"
        assert telemetry["input_tokens"] == 0
        assert telemetry["output_tokens"] == 0
        assert telemetry["cost_usd"] == 0.0
        assert telemetry["duration_ms"] >= 0
        assert telemetry["tool_call_count"] == len(result["tools_used"])
        assert telemetry["invocation_id"].startswith("agent_invocation_")

    assert public["evidence"]
    for evidence in public["evidence"]:
        correlation = evidence["correlation"]
        assert correlation["incident_id"] == report.incident_id
        assert correlation["batch_id"]
        assert correlation["airflow_run_id"]
        assert correlation["dbt_invocation_id"]
        assert correlation["quality_run"] == report.incident_id
