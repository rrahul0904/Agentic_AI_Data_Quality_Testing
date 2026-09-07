"""Local-first environment doctor with honest optional-integration status."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _command(name: str, *, args: tuple[str, ...] = ("--version",)) -> dict[str, str]:
    executable = shutil.which(name)
    if not executable:
        return {"status": "WARN", "detail": f"{name} not installed"}
    try:
        completed = subprocess.run([executable, *args], capture_output=True, text=True, timeout=5, check=False)
        detail = (completed.stdout or completed.stderr).strip().splitlines()[0]
        return {"status": "PASS" if completed.returncode == 0 else "WARN", "detail": detail or executable}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "WARN", "detail": str(exc)}


def _module(name: str, label: str) -> dict[str, str]:
    try:
        installed = importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        installed = False
    return {"status": "PASS", "detail": f"{label} installed"} if installed else {"status": "WARN", "detail": f"{label} not installed"}


def run_doctor(project: str | Path = ".") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    checks: dict[str, dict[str, str]] = {
        "python": {"status": "PASS", "detail": platform.python_version()},
        "node": _command("node"),
        "dbt": _command("dbt"),
        "airflow": _command("airflow"),
        "postgresql": _command("psql"),
        "oracle_client": _command("sqlplus", args=("-V",)),
        "ollama": _command("ollama"),
        "snowflake_connector": _module("snowflake.connector", "Snowflake Python connector"),
        "project_config": {"status": "PASS" if root.is_dir() else "FAIL", "detail": str(root)},
    }
    docker = _command("docker")
    if docker["status"] == "PASS":
        try:
            result = subprocess.run([shutil.which("docker") or "docker", "info"], capture_output=True, text=True, timeout=5, check=False)
            docker = {"status": "PASS" if result.returncode == 0 else "SKIP", "detail": "Docker daemon available" if result.returncode == 0 else "Docker daemon unavailable"}
        except (OSError, subprocess.TimeoutExpired):
            docker = {"status": "SKIP", "detail": "Docker daemon unavailable"}
    checks["docker"] = docker
    sf_required = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
    checks["snowflake_credentials"] = {
        "status": "PASS" if all(os.getenv(key) for key in sf_required) else "SKIP",
        "detail": "configured" if all(os.getenv(key) for key in sf_required) else "Snowflake credentials unavailable",
    }
    shiftforge = root / "shiftforge"
    if root.name == "hospitality-snowflake-data-platform":
        shiftforge = root.parent / "shiftforge"
    checks["shiftforge"] = {"status": "PASS" if (shiftforge / "pyproject.toml").is_file() else "WARN", "detail": str(shiftforge)}
    overall = "FAIL" if any(item["status"] == "FAIL" for item in checks.values()) else "PASS"
    return {"status": overall, "mode": "LOCAL", "checks": checks}
