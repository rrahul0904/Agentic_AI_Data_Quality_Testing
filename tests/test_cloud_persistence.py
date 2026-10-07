from __future__ import annotations

import inspect
import os

import pytest

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
