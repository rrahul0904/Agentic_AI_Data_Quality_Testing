from __future__ import annotations

import inspect
import os

import pytest

from agentic_data_platform.agents.contracts import (
    AgentHypothesis,
    EvidenceRecord,
    EvidenceTier,
    HypothesisStatus,
    IncidentState,
    RemediationPlan,
)
from agentic_data_platform.agents.postgres_store import PostgresInvestigationStore
from agentic_data_platform.agents.store import InvestigationStore
from agentic_data_platform.agents.store_factory import create_investigation_store, investigation_backend_name
from agentic_data_platform.models import ApprovalRecord, Environment, ProjectRecord, RunRecord
from agentic_data_platform.persistence.factory import create_control_plane_repository, persistence_backend_name
from agentic_data_platform.persistence.postgres import PostgresControlPlaneRepository
from agentic_data_platform.persistence.repositories import ControlPlaneRepository
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository


def test_repository_contract_includes_production_approval_lifecycle() -> None:
    abstract = ControlPlaneRepository.__abstractmethods__
    assert "get_approval" in abstract
    assert "consume_approval" in abstract
    assert not inspect.isabstract(SQLiteControlPlaneRepository)
    assert not inspect.isabstract(PostgresControlPlaneRepository)


def test_factory_keeps_sqlite_as_local_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ADE_DATABASE_URL", raising=False)
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))

    repository = create_control_plane_repository()

    assert isinstance(repository, SQLiteControlPlaneRepository)
    assert persistence_backend_name(repository) == "sqlite"
    repository.initialize()
    repository.save_project(ProjectRecord(name="prototype"))
    assert repository.list_records("projects")[0]["name"] == "prototype"


def test_factory_selects_postgres_without_connecting() -> None:
    repository = create_control_plane_repository("postgresql://ade:secret@db.internal:5432/ade")

    assert isinstance(repository, PostgresControlPlaneRepository)
    assert persistence_backend_name(repository) == "postgresql"
    assert repository.dsn.endswith("/ade")


def test_factory_fails_closed_for_unknown_remote_backend() -> None:
    with pytest.raises(ValueError, match="unsupported control-plane persistence scheme"):
        create_control_plane_repository("mysql://example/control")


def _assert_single_use_approval(repository: ControlPlaneRepository) -> None:
    repository.initialize()

    project = ProjectRecord(name="prototype")
    run = RunRecord(project_id=project.project_id, environment_id="env_demo", intent="repair")
    approval = ApprovalRecord(
        run_id=run.run_id,
        approved_by="operator",
        scope="dbt_build",
        environment=Environment.PROD,
    )

    repository.save_project(project)
    repository.save_run(run)
    repository.save_approval(approval)

    stored_run = repository.get_run(run.run_id)
    assert stored_run is not None
    assert stored_run.intent == "repair"
    assert repository.has_approval(run.run_id, "dbt_build", environment="prod")
    stored_approval = repository.get_approval(approval.approval_id)
    assert stored_approval is not None
    assert stored_approval["used_at"] is None

    repository.consume_approval(approval.approval_id)

    assert not repository.has_approval(run.run_id, "dbt_build", environment="prod")
    consumed = repository.get_approval(approval.approval_id)
    assert consumed is not None
    assert consumed["used_at"] is not None


def test_sqlite_approval_is_single_use(tmp_path) -> None:
    _assert_single_use_approval(SQLiteControlPlaneRepository(tmp_path / "approval.db"))


def test_postgres_repository_preserves_single_use_approval_contract() -> None:
    dsn = os.getenv("ADE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ADE_TEST_POSTGRES_DSN is not configured")

    repository = PostgresControlPlaneRepository(dsn)
    _assert_single_use_approval(repository)

    runs = repository.list_records("runs")
    approvals = repository.list_records("approvals")
    assert any(row["intent"] == "repair" for row in runs)
    assert any(row["scope"] == "dbt_build" for row in approvals)


def test_investigation_factory_keeps_sqlite_local(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ADE_INVESTIGATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("ADE_INVESTIGATION_DATABASE", str(tmp_path / "investigations.db"))

    store = create_investigation_store()

    assert isinstance(store, InvestigationStore)
    assert investigation_backend_name(store) == "sqlite"


def test_investigation_factory_selects_postgres_without_connecting(monkeypatch) -> None:
    class DeferredPostgresStore(PostgresInvestigationStore):
        def initialize(self) -> None:
            return None

    monkeypatch.setattr("agentic_data_platform.agents.store_factory.PostgresInvestigationStore", DeferredPostgresStore)
    store = create_investigation_store("postgresql://ade:secret@db.internal:5432/ade")

    assert isinstance(store, DeferredPostgresStore)
    assert store.dsn.endswith("/ade")


def test_investigation_factory_fails_closed_for_unknown_remote_backend() -> None:
    with pytest.raises(ValueError, match="unsupported investigation persistence scheme"):
        create_investigation_store("redis://example/0")


def _assert_investigation_contract(store: InvestigationStore | PostgresInvestigationStore) -> None:
    incident_id = store.create_incident(
        "prototype_cloud_failure",
        "Prototype cloud failure",
        "mart.customer_revenue",
        {"signal": "row_count_drop", "expected": 100, "actual": 72},
        mode="PROTOTYPE_CLOUD",
    )
    incident = store.incident(incident_id)
    assert incident["state"] == IncidentState.DETECTED.value
    assert incident["approved"] is False

    evidence = EvidenceRecord(
        kind="row_count",
        source="quality.reconciliation",
        summary="Target row count dropped from 100 to 72",
        payload={"expected": 100, "actual": 72},
        tier=EvidenceTier.DIRECT_MEASUREMENT,
        correlation={"asset": "mart.customer_revenue"},
    )
    store.save_evidence(incident_id, evidence)
    with pytest.raises(ValueError, match="immutable evidence already exists"):
        store.save_evidence(incident_id, evidence)

    hypothesis = AgentHypothesis(
        name="upstream_filter_regression",
        statement="A newly narrowed upstream filter removed valid rows",
        status=HypothesisStatus.SUPPORTED,
        confidence=0.94,
        supporting_evidence_ids=(evidence.evidence_id,),
    )
    store.save_hypothesis(incident_id, hypothesis)
    assert store.hypotheses(incident_id)[0]["status"] == HypothesisStatus.SUPPORTED.value

    store.save_mappings(
        incident_id,
        [
            {
                "source": "stg.customer_revenue",
                "target": "mart.customer_revenue",
                "mapping_type": "lineage",
                "expression": {"model": "customer_revenue"},
            }
        ],
    )
    assert store.mappings(incident_id)[0]["target"] == "mart.customer_revenue"

    store.save_certification(
        incident_id,
        "mart.customer_revenue",
        "FAILED",
        "row-count parity failed",
        evidence_ids=(evidence.evidence_id,),
    )
    assert store.latest_certifications(incident_id)[0]["status"] == "FAILED"

    transitions = [
        IncidentState.INVESTIGATING,
        IncidentState.EVIDENCE_COLLECTION,
        IncidentState.RCA,
        IncidentState.IMPACT_ANALYSIS,
        IncidentState.REMEDIATION_PROPOSED,
        IncidentState.AWAITING_APPROVAL,
    ]
    for state in transitions:
        store.transition(incident_id, state, f"advance to {state.value}")

    plan = RemediationPlan(
        action="rebuild affected dbt model",
        reason="restore rows removed by the regressed filter",
        evidence_ids=(evidence.evidence_id,),
        risk="medium",
        blast_radius=("mart.customer_revenue",),
        rollback="restore previous model revision",
        verification_plan=("dbt test", "row-count parity"),
        arguments={"selective_recovery": {"dbt_command": "dbt build --select customer_revenue"}},
    )
    store.save_remediation(incident_id, plan)
    approval = store.approve(incident_id, approved_by="prototype-operator")
    assert approval["approved"] is True
    assert store.remediation(incident_id)["status"] == "APPROVED"

    store.update_outcome(
        incident_id,
        first_divergence="stg.customer_revenue",
        root_cause="upstream filter regression",
        root_cause_confidence=0.94,
        blast_radius=["mart.customer_revenue", "dashboard.revenue"],
        certification="AT_RISK",
        execution_result={"status": "planned"},
        verification_result={"status": "pending"},
    )
    updated = store.incident(incident_id)
    assert updated["approved"] is True
    assert updated["root_cause_confidence"] == pytest.approx(0.94)
    assert updated["blast_radius"] == ["mart.customer_revenue", "dashboard.revenue"]
    assert len(store.evidence(incident_id)) == 1
    assert len(store.transitions(incident_id)) == len(transitions)


def test_sqlite_investigation_contract(tmp_path) -> None:
    _assert_investigation_contract(InvestigationStore(tmp_path / "incident.db"))


def test_postgres_investigation_contract() -> None:
    dsn = os.getenv("ADE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ADE_TEST_POSTGRES_DSN is not configured")
    _assert_investigation_contract(PostgresInvestigationStore(dsn))
