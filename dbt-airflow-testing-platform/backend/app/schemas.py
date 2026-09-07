from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# dbt projects
# ---------------------------------------------------------------------------


class DbtProjectCreate(BaseModel):
    name: str
    execution_mode: str  # "local" | "cloud"
    # local mode
    adapter: str | None = None  # "duckdb" | "snowflake"
    # cloud mode
    dbt_cloud_host: str | None = None
    dbt_cloud_account_id: str | None = None
    dbt_cloud_project_id: str | None = None
    dbt_cloud_api_token: str | None = None


class DbtJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    kind: str
    select_str: str | None = None
    dbt_cloud_job_id: str | None = None
    schedule_description: str | None = None


class DbtJobCreate(BaseModel):
    name: str
    select_str: str  # local mode only; cloud jobs come from sync-jobs


class DbtProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime
    status: str
    error_message: str | None = None
    execution_mode: str
    adapter: str | None = None
    dbt_cloud_host: str | None = None
    dbt_cloud_account_id: str | None = None
    dbt_cloud_project_id: str | None = None
    lineage_refreshed_at: datetime | None = None
    project_dir: str | None = None  # local mode only -- lets tooling (e.g. scripts/run_revenue_demo.py) find the workspace
    venv_path: str | None = None
    profiles_dir: str | None = None


class DbtProjectDetail(DbtProjectOut):
    jobs: list[DbtJobOut] = []


# ---------------------------------------------------------------------------
# Airflow projects
# ---------------------------------------------------------------------------


class AirflowProjectCreate(BaseModel):
    name: str


class AirflowDagRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dag_id: str
    schedule_interval: str | None = None
    is_paused: bool
    tags: list | None = None


class AirflowProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime
    status: str
    error_message: str | None = None
    base_url: str | None = None
    admin_username: str | None = None
    is_running: bool = False


class AirflowProjectDetail(AirflowProjectOut):
    dags: list[AirflowDagRefOut] = []


class LineageOut(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunCreateRequest(BaseModel):
    dbt_project_id: str | None = None
    dbt_job_ids: list[str] | None = None  # empty/None = run the whole project (local) via default select
    dbt_select: str | None = None  # ad-hoc local run without a saved DbtJob
    airflow_project_id: str | None = None
    airflow_dag_ids: list[str] | None = None
    triggered_by: str = "ui"


class DbtTestResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    unique_id: str
    node_kind: str
    name: str
    status: str
    execution_time: float
    message: str | None = None
    relation_name: str | None = None


class DbtJobRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    label: str
    mode: str
    status: str
    dbt_cloud_run_id: str | None = None
    results: list[DbtTestResultOut] = []


class AirflowTaskResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    task_id: str
    state: str
    duration: float | None = None
    try_number: int
    note: str | None = None


class AirflowDagRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dag_id: str
    airflow_dag_run_id: str | None = None
    state: str
    logical_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    tasks: list[AirflowTaskResultOut] = []


class TestRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    finished_at: datetime | None = None
    status: str
    triggered_by: str
    error_message: str | None = None
    dbt_project_id: str | None = None
    airflow_project_id: str | None = None


class TestRunDetail(TestRunSummary):
    dbt_job_runs: list[DbtJobRunOut] = []
    airflow_dag_runs: list[AirflowDagRunOut] = []
