from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PLATFORM_DIR = BACKEND_DIR.parent

PROJECTS_ROOT = BACKEND_DIR / "data" / "projects"  # per-project venvs/workspaces live here
SCRIPTS_DIR = PLATFORM_DIR / "scripts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'testctl.db'}"

    # Provisioning new dbt-core venvs (one per local DbtProject)
    dbt_core_version_spec: str = "dbt-core>=1.10"
    dbt_adapter_specs: dict[str, str] = {
        "duckdb": "dbt-duckdb>=1.10",
        "snowflake": "dbt-snowflake>=1.10",
    }

    # Provisioning new Airflow instances (one per AirflowProject)
    airflow_version: str = "2.10.5"

    # dbt Cloud
    dbt_cloud_request_timeout_seconds: int = 15

    airflow_request_timeout_seconds: int = 10
    poll_interval_seconds: float = 2.0
    run_timeout_seconds: int = 600

    # LLM Gateway (Architecture spec Section 23) -- only used to escalate RCA
    # when the deterministic lineage walk can't localize a single root cause
    # (see services/rca.py). Never required for the deterministic path.
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"  # cheap/fast model -- RCA-from-evidence is a bounded, structured task
    llm_request_timeout_seconds: int = 30


settings = Settings()
