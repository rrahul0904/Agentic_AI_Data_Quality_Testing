from __future__ import annotations

from agentic_data_platform.agents import (
    AgentRole,
    IncidentState,
    InvestigationStore,
    SupervisorAgent,
    agent_roster,
    benchmark_catalog,
    scenario_catalog,
)
from agentic_data_platform.tools.builtin import build_tool_registry


def supervisor(tmp_path):
    project = tmp_path.parents[0] / "missing"
    # The agentic scenario engine is deliberately robust when repository graph artifacts are unavailable;
    # it still uses scenario mappings and deterministic evidence rather than inventing metadata.
    return SupervisorAgent(build_tool_registry(), InvestigationStore(tmp_path / "incidents.db"), project)


def test_roster_contains_twelve_first_class_roles():
    roster = agent_roster()
    assert len(roster) == 12
    assert {item["role"] for item in roster} == {role.value for role in AgentRole}


def test_scenario_library_contains_all_required_failures():
    scenarios = scenario_catalog()
    assert len(scenarios) == 18
    assert "airflow_green_data_bad" in {item["scenario_id"] for item in scenarios}


def test_watermark_investigation_is_dynamic_and_waits_for_approval(tmp_path):
    service = supervisor(tmp_path)
    report = service.investigate("watermark_defect")
    assert report.state is IncidentState.AWAITING_APPROVAL
    assert report.first_divergence == "source→raw"
    assert report.root_cause == "WATERMARK_ADVANCED_BEYOND_EXTRACT"
    assert report.remediation is not None and report.remediation.requires_approval
    roles = [item.role for item in report.agent_results]
    assert AgentRole.TRANSFORMATION not in roles
    assert AgentRole.RCA in roles
    assert AgentRole.IMPACT in roles
    assert AgentRole.REMEDIATION in roles
    assert report.certification == "FAILED"


def test_dbt_divergence_delegates_to_transformation_agent(tmp_path):
    service = supervisor(tmp_path)
    report = service.investigate("dbt_filter_defect")
    assert report.root_cause == "DBT_FILTER_EXCLUDES_VALID_STATUS"
    assert report.first_divergence == "staging→intermediate"
    assert AgentRole.TRANSFORMATION in [item.role for item in report.agent_results]


def test_approval_execution_verification_and_recertification(tmp_path):
    service = supervisor(tmp_path)
    pending = service.investigate("watermark_defect")
    resolved = service.approve_and_execute(pending.incident_id, approved_by="test-operator")
    assert resolved.state is IncidentState.RESOLVED
    assert resolved.approved is True
    assert resolved.execution_result["mode"] == "LOCAL_PROVING_GROUND"
    assert resolved.verification_result["status"] == "PASS"
    assert resolved.certification == "CERTIFIED"


def test_all_scenarios_localize_expected_root_cause_and_divergence(tmp_path):
    service = supervisor(tmp_path)
    for item in benchmark_catalog():
        report = service.investigate(item["scenario_id"])
        assert report.root_cause == item["expected_root_cause"], item["scenario_id"]
        assert report.first_divergence == item["expected_first_divergence"], item["scenario_id"]


def test_invalid_execution_without_approval_is_rejected(tmp_path):
    service = supervisor(tmp_path)
    pending = service.investigate("watermark_defect")
    service.store.connection.execute("UPDATE incidents SET state=? WHERE incident_id=?", (IncidentState.INVESTIGATING.value, pending.incident_id))
    service.store.connection.commit()
    try:
        service.approve_and_execute(pending.incident_id, approved_by="operator")
    except ValueError as exc:
        assert "AWAITING_APPROVAL" in str(exc)
    else:
        raise AssertionError("approval boundary was bypassed")
