from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in (
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
        "ADE_DBT_LIVE_MUTATION_APPROVED",
        "OPENAI_API_KEY",
        "ADE_LIVE_AGENT_PROVIDER",
        "ADE_LIVE_AGENT_MODEL",
        "ADE_AIRFLOW_BASE_URL",
        "ADE_AIRFLOW_VERSION",
        "ADE_AIRFLOW_TOKEN",
        "ADE_AIRFLOW_USERNAME",
        "ADE_AIRFLOW_PASSWORD",
        "ADE_AIRFLOW_LIVE_MUTATION_APPROVED",
    ):
        env.pop(name, None)
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def test_live_scripts_fail_closed_without_external_configuration():
    for script in (
        "scripts/live_snowflake_e2e.py",
        "scripts/live_dbt_e2e.py",
        "scripts/live_agent_e2e.py",
        "scripts/live_airflow_e2e.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(ROOT / script)],
            env=_clean_env(),
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode != 0, script
        assert "BLOCKED_EXTERNAL" in output, (script, output)


def test_live_workflow_has_safe_preflight_and_all_required_jobs():
    text = (ROOT / ".github/workflows/live-e2e.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "preflight:" in text
    assert "LIVE PREFLIGHT: BLOCKED_EXTERNAL" in text
    assert "vars.ADE_LIVE_RELEASE_AUTO == 'true'" in text
    for job in (
        "live-snowflake-e2e:",
        "live-dbt-e2e:",
        "live-agent-e2e:",
        "live-airflow-e2e:",
    ):
        assert job in text
    assert "secrets.SNOWFLAKE_PASSWORD" in text
    assert "secrets.OPENAI_API_KEY" in text
    assert "secrets.ADE_AIRFLOW_BASE_URL" in text
    assert "secrets.ADE_DBT_LIVE_MUTATION_APPROVED" in text
    assert "secrets.ADE_AIRFLOW_LIVE_MUTATION_APPROVED" in text
