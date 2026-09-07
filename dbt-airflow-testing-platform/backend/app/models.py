import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# dbt projects
# ---------------------------------------------------------------------------


class DbtProject(Base):
    """A named dbt workspace: either a locally-run dbt-core project (its own
    isolated venv + adapter) or a pointer to an existing dbt Cloud project
    (jobs run via dbt Cloud's API, nothing executes locally)."""

    __tablename__ = "dbt_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    status: Mapped[str] = mapped_column(String, default="PROVISIONING")
    # PROVISIONING -> READY | ERROR
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution_mode: Mapped[str] = mapped_column(String)  # "local" | "cloud"

    # --- local mode ---
    adapter: Mapped[str | None] = mapped_column(String, nullable=True)  # duckdb|snowflake|bigquery|databricks|postgres
    venv_path: Mapped[str | None] = mapped_column(String, nullable=True)
    project_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    profiles_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    dbt_target: Mapped[str] = mapped_column(String, default="dev")

    # --- cloud mode ---
    dbt_cloud_host: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. cloud.getdbt.com
    dbt_cloud_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dbt_cloud_project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dbt_cloud_api_token: Mapped[str | None] = mapped_column(String, nullable=True)  # never returned by the API

    lineage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    jobs: Mapped[list["DbtJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class DbtJob(Base):
    """One runnable/selectable unit inside a DbtProject: a saved dbt --select
    string for local projects, or a synced dbt Cloud job for cloud projects."""

    __tablename__ = "dbt_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dbt_project_id: Mapped[str] = mapped_column(ForeignKey("dbt_projects.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # "local_select" | "cloud_job"
    select_str: Mapped[str | None] = mapped_column(String, nullable=True)  # local mode
    dbt_cloud_job_id: Mapped[str | None] = mapped_column(String, nullable=True)  # cloud mode
    schedule_description: Mapped[str | None] = mapped_column(String, nullable=True)  # informational only

    project: Mapped[DbtProject] = relationship(back_populates="jobs")


# ---------------------------------------------------------------------------
# Airflow projects
# ---------------------------------------------------------------------------


class AirflowProject(Base):
    """A dedicated, auto-provisioned Airflow instance (its own venv, metadata
    DB, and webserver/scheduler/triggerer processes on a unique port)."""

    __tablename__ = "airflow_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    status: Mapped[str] = mapped_column(String, default="PROVISIONING")
    # PROVISIONING -> READY | ERROR ; READY -> STOPPED (via stop) -> READY (via start)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    venv_path: Mapped[str | None] = mapped_column(String, nullable=True)
    airflow_home: Mapped[str | None] = mapped_column(String, nullable=True)
    webserver_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    admin_username: Mapped[str | None] = mapped_column(String, nullable=True)
    admin_password: Mapped[str | None] = mapped_column(String, nullable=True)

    webserver_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduler_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggerer_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)

    dags: Mapped[list["AirflowDagRef"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class AirflowDagRef(Base):
    """One DAG discovered (via `GET /dags`) inside an AirflowProject, with its
    schedule and dependency graph cached for display."""

    __tablename__ = "airflow_dag_refs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    airflow_project_id: Mapped[str] = mapped_column(ForeignKey("airflow_projects.id"))

    dag_id: Mapped[str] = mapped_column(String)
    schedule_interval: Mapped[str | None] = mapped_column(String, nullable=True)
    is_paused: Mapped[bool] = mapped_column(Integer, default=0)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    lineage_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # task nodes + dependency edges

    project: Mapped[AirflowProject] = relationship(back_populates="dags")


# ---------------------------------------------------------------------------
# Test runs (a run may exercise one or more dbt jobs and/or Airflow DAGs)
# ---------------------------------------------------------------------------


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String, default="PENDING")
    # PENDING -> RUNNING -> PASSED | FAILED | ERROR
    triggered_by: Mapped[str] = mapped_column(String, default="ui")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    dbt_project_id: Mapped[str | None] = mapped_column(ForeignKey("dbt_projects.id"), nullable=True)
    dbt_job_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # selected DbtJob.id list
    dbt_adhoc_select: Mapped[str | None] = mapped_column(String, nullable=True)  # local mode, no saved DbtJob

    airflow_project_id: Mapped[str | None] = mapped_column(ForeignKey("airflow_projects.id"), nullable=True)
    airflow_dag_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # selected dag_id strings

    dbt_job_runs: Mapped[list["DbtJobRun"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    airflow_dag_runs: Mapped[list["AirflowDagRun"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class DbtJobRun(Base):
    """One dbt job's execution within a TestRun (a TestRun may run several
    jobs from the same project, or none, in parallel)."""

    __tablename__ = "dbt_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"))
    dbt_job_id: Mapped[str | None] = mapped_column(ForeignKey("dbt_jobs.id"), nullable=True)

    label: Mapped[str] = mapped_column(String)  # job name / select string, for display
    mode: Mapped[str] = mapped_column(String)  # "local" | "cloud"
    status: Mapped[str] = mapped_column(String, default="RUNNING")  # PASSED | FAILED | ERROR
    dbt_cloud_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[TestRun] = relationship(back_populates="dbt_job_runs")
    results: Mapped[list["DbtTestResult"]] = relationship(back_populates="job_run", cascade="all, delete-orphan")


class DbtTestResult(Base):
    __tablename__ = "dbt_test_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dbt_job_run_id: Mapped[str] = mapped_column(ForeignKey("dbt_job_runs.id"))

    unique_id: Mapped[str] = mapped_column(String)
    node_kind: Mapped[str] = mapped_column(String)  # model | test | seed | snapshot
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # pass | fail | error | skipped | success
    execution_time: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    relation_name: Mapped[str | None] = mapped_column(String, nullable=True)

    job_run: Mapped[DbtJobRun] = relationship(back_populates="results")


class AirflowDagRun(Base):
    __tablename__ = "airflow_dag_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"))

    dag_id: Mapped[str] = mapped_column(String)
    airflow_dag_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, default="PENDING")
    logical_date: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[str | None] = mapped_column(String, nullable=True)
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)

    run: Mapped[TestRun] = relationship(back_populates="airflow_dag_runs")
    tasks: Mapped[list["AirflowTaskResult"]] = relationship(
        back_populates="dag_run", cascade="all, delete-orphan"
    )


class AirflowTaskResult(Base):
    __tablename__ = "airflow_task_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    airflow_dag_run_pk: Mapped[str] = mapped_column(ForeignKey("airflow_dag_runs.id"))

    task_id: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    try_number: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    dag_run: Mapped[AirflowDagRun] = relationship(back_populates="tasks")


class Artifact(Base):
    """Raw evidence blobs (run_results.json, manifest excerpt, Airflow/dbt
    Cloud API responses)."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"))
    kind: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[TestRun] = relationship(back_populates="artifacts")
