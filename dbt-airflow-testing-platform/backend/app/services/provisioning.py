"""Provisions per-project isolated environments.

- A local DbtProject gets its own venv (dbt-core + one adapter) and a
  scaffolded dbt project (`dbt init`), so different projects can run
  different dbt/adapter versions without stepping on each other.
- An AirflowProject gets its own venv, its own AIRFLOW_HOME/metadata DB, a
  freshly allocated port, and its own webserver/scheduler/triggerer
  processes -- a fully independent Airflow instance per project, not a
  shared one, per the same reasoning as the dbt venv isolation.

Every function here does real, synchronous, possibly slow work (pip
installs, `dbt init`, `airflow db migrate`, process starts) and is meant to
be called via `asyncio.to_thread` from request-handling code, mirroring how
dbt_runner.py/airflow_client.py's blocking calls are already used.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

from ..config import PROJECTS_ROOT, SCRIPTS_DIR, settings


class ProvisioningError(RuntimeError):
    pass


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise ProvisioningError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"--- stdout (tail) ---\n{result.stdout[-3000:]}\n"
            f"--- stderr (tail) ---\n{result.stderr[-3000:]}"
        )
    return result


def _create_venv(venv_path: Path) -> Path:
    venv_path.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "venv", str(venv_path)])
    return venv_path / "bin" / "python3"


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "project"


# ---------------------------------------------------------------------------
# dbt: local project provisioning
# ---------------------------------------------------------------------------

_DUCKDB_PROFILE = """{profile_name}:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: {warehouse_path}
      threads: 4
"""

# Credentials are read from env vars at `dbt` invocation time -- never stored
# by this tool. Set them in the shell/service that runs the backend.
_SNOWFLAKE_PROFILE = """{profile_name}:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: "{{{{ env_var('SNOWFLAKE_ACCOUNT') }}}}"
      user: "{{{{ env_var('SNOWFLAKE_USER') }}}}"
      password: "{{{{ env_var('SNOWFLAKE_PASSWORD') }}}}"
      role: "{{{{ env_var('SNOWFLAKE_ROLE', 'TRANSFORMER') }}}}"
      database: "{{{{ env_var('SNOWFLAKE_DATABASE') }}}}"
      warehouse: "{{{{ env_var('SNOWFLAKE_WAREHOUSE') }}}}"
      schema: "{{{{ env_var('SNOWFLAKE_SCHEMA', 'public') }}}}"
      threads: 4
"""

_PROFILE_TEMPLATES = {"duckdb": _DUCKDB_PROFILE, "snowflake": _SNOWFLAKE_PROFILE}


def provision_dbt_local_project(project_id: str, name: str, adapter: str) -> dict:
    if adapter not in settings.dbt_adapter_specs:
        raise ValueError(f"unsupported adapter '{adapter}'; choose one of {list(settings.dbt_adapter_specs)}")

    root = PROJECTS_ROOT / "dbt" / project_id
    venv_path = root / "venv"
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    python_bin = _create_venv(venv_path)
    _run([str(python_bin), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    _run(
        [
            str(python_bin), "-m", "pip", "install", "-q",
            settings.dbt_core_version_spec, settings.dbt_adapter_specs[adapter],
        ]
    )

    dbt_bin = venv_path / "bin" / "dbt"
    slug = _safe_name(name)

    # dbt-core 1.10+ dropped `dbt init --adapter` entirely (verified against
    # the pinned dbt-core version); --skip-profile-setup alone is enough to
    # scaffold a generic project non-interactively, since we write our own
    # adapter-specific profiles.yml right after. stdin is closed as a safety
    # net against any stray prompt from a different dbt-core version.
    _run(
        [str(dbt_bin), "init", slug, "--skip-profile-setup"],
        cwd=str(workspace),
        stdin=subprocess.DEVNULL,
    )

    project_dir = workspace / slug
    profiles_dir = project_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    if adapter == "duckdb":
        warehouse_dir = project_dir / "warehouse"
        warehouse_dir.mkdir(parents=True, exist_ok=True)
        profile_content = _PROFILE_TEMPLATES[adapter].format(
            profile_name=slug, warehouse_path=str(warehouse_dir / "warehouse.duckdb")
        )
    else:
        profile_content = _PROFILE_TEMPLATES[adapter].format(profile_name=slug)
    (profiles_dir / "profiles.yml").write_text(profile_content)

    # dbt_project.yml's `profile:` key must match the profiles.yml key above.
    dbt_project_yml = project_dir / "dbt_project.yml"
    content = dbt_project_yml.read_text()
    content = re.sub(r"(?m)^profile:\s*.*$", f"profile: '{slug}'", content)
    dbt_project_yml.write_text(content)

    return {
        "venv_path": str(venv_path),
        "project_dir": str(project_dir),
        "profiles_dir": str(profiles_dir),
        "adapter": adapter,
    }


# ---------------------------------------------------------------------------
# dbt: cloud project provisioning (no local install -- validate creds only)
# ---------------------------------------------------------------------------


def validate_dbt_cloud_credentials(host: str, account_id: str, api_token: str) -> None:
    from .dbt_cloud_client import DbtCloudApiError, DbtCloudClient

    client = DbtCloudClient(host=host, account_id=account_id, api_token=api_token)
    try:
        client.validate_credentials()
    except (DbtCloudApiError, requests.RequestException) as exc:
        raise ProvisioningError(f"could not validate dbt Cloud credentials: {exc}") from exc


# ---------------------------------------------------------------------------
# Airflow: dedicated per-project instance provisioning
# ---------------------------------------------------------------------------


def _airflow_env(airflow_home: Path, venv_path: Path) -> dict:
    env = os.environ.copy()
    env["AIRFLOW_HOME"] = str(airflow_home)
    env["AIRFLOW__CORE__LOAD_EXAMPLES"] = "false"
    env["AIRFLOW__API__AUTH_BACKENDS"] = "airflow.api.auth.backend.basic_auth"
    # Default is 300s -- far too slow for "upload a DAG, sync it" in a UI.
    env["AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL"] = "10"
    # See docs/RUNBOOK.md -- StandardTaskRunner forks by default, which
    # deadlocks in some sandboxed/macOS setups. patch_airflow_entrypoint.py
    # (run below, once per provisioned venv) makes this env var flip
    # airflow.settings.CAN_FORK off; harmless where it isn't needed.
    env["ADE_FORCE_EXEC_TASK_RUNNER"] = "1"
    # SequentialExecutor shells out to the bare `airflow` command by name
    # (not sys.executable-relative) to run each task -- without this
    # project's own venv on PATH, that lookup fails with FileNotFoundError
    # and every task sits in "queued" forever. This is what `source
    # venv/bin/activate` would do for PATH; we're doing it for a
    # subprocess's env instead of the current shell.
    env["PATH"] = f"{venv_path / 'bin'}:{env.get('PATH', '')}"
    return env


def _start_background(cmd: list[str], env: dict, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "a")
    proc = subprocess.Popen(cmd, env=env, stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid


def _wait_for_health(base_url: str, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/api/v1/health", timeout=5)
            if resp.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(2)
    raise ProvisioningError(f"Airflow webserver at {base_url} did not become healthy in time: {last_error}")


def provision_airflow_project(project_id: str) -> dict:
    root = PROJECTS_ROOT / "airflow" / project_id
    venv_path = root / "venv"
    airflow_home = root / "home"
    (airflow_home / "dags").mkdir(parents=True, exist_ok=True)

    python_bin = _create_venv(venv_path)
    _run([str(python_bin), "-m", "pip", "install", "-q", "--upgrade", "pip"])

    py_mm = f"{sys.version_info.major}.{sys.version_info.minor}"
    constraint_url = (
        f"https://raw.githubusercontent.com/apache/airflow/"
        f"constraints-{settings.airflow_version}/constraints-{py_mm}.txt"
    )
    _run(
        [
            str(python_bin), "-m", "pip", "install", "-q",
            f"apache-airflow=={settings.airflow_version}", "--constraint", constraint_url,
        ]
    )
    _run([str(python_bin), "-m", "pip", "install", "-q", "duckdb"])

    _run([sys.executable, str(SCRIPTS_DIR / "patch_airflow_entrypoint.py"), str(venv_path)])

    airflow_bin = venv_path / "bin" / "airflow"
    env = _airflow_env(airflow_home, venv_path)

    _run([str(airflow_bin), "db", "migrate"], env=env)

    admin_password = uuid.uuid4().hex[:16]
    _run(
        [
            str(airflow_bin), "users", "create",
            "--username", "admin", "--password", admin_password,
            "--firstname", "Admin", "--lastname", "User",
            "--role", "Admin", "--email", "admin@example.com",
        ],
        env=env,
    )

    port = find_free_port()
    log_dir = root / "logs"
    webserver_pid = _start_background(
        [str(airflow_bin), "webserver", "--debug", "--port", str(port)], env, log_dir / "webserver.log"
    )
    scheduler_pid = _start_background(
        [str(airflow_bin), "scheduler", "--skip-serve-logs"], env, log_dir / "scheduler.log"
    )
    triggerer_pid = _start_background(
        [str(airflow_bin), "triggerer", "--skip-serve-logs"], env, log_dir / "triggerer.log"
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_url)
    except ProvisioningError:
        for pid in (webserver_pid, scheduler_pid, triggerer_pid):
            _kill(pid)
        raise

    return {
        "venv_path": str(venv_path),
        "airflow_home": str(airflow_home),
        "webserver_port": port,
        "base_url": base_url,
        "admin_username": "admin",
        "admin_password": admin_password,
        "webserver_pid": webserver_pid,
        "scheduler_pid": scheduler_pid,
        "triggerer_pid": triggerer_pid,
    }


def _kill(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def stop_airflow_project(project) -> None:
    for pid in (project.webserver_pid, project.scheduler_pid, project.triggerer_pid):
        _kill(pid)


def start_airflow_project(project) -> dict:
    airflow_home = Path(project.airflow_home)
    venv_path = Path(project.venv_path)
    airflow_bin = venv_path / "bin" / "airflow"
    env = _airflow_env(airflow_home, venv_path)
    log_dir = venv_path.parent / "logs"

    webserver_pid = _start_background(
        [str(airflow_bin), "webserver", "--debug", "--port", str(project.webserver_port)],
        env, log_dir / "webserver.log",
    )
    scheduler_pid = _start_background(
        [str(airflow_bin), "scheduler", "--skip-serve-logs"], env, log_dir / "scheduler.log"
    )
    triggerer_pid = _start_background(
        [str(airflow_bin), "triggerer", "--skip-serve-logs"], env, log_dir / "triggerer.log"
    )
    _wait_for_health(project.base_url)
    return {"webserver_pid": webserver_pid, "scheduler_pid": scheduler_pid, "triggerer_pid": triggerer_pid}


def is_process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, TypeError):
        return False
