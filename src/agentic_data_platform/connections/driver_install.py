"""Allowlisted warehouse driver installation planning/execution."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from typing import Any, Callable


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

_DRIVERS = {
    "snowflake": ("snowflake.connector", "snowflake-connector-python"),
    "bigquery": ("google.cloud.bigquery", "google-cloud-bigquery"),
    "databricks": ("databricks.sql", "databricks-sql-connector"),
    "postgres": ("psycopg", "psycopg[binary]"),
    "postgresql": ("psycopg", "psycopg[binary]"),
    "redshift": ("psycopg", "psycopg[binary]"),
    "mysql": ("pymysql", "PyMySQL"),
    "sqlserver": ("pyodbc", "pyodbc"),
    "fabric": ("pyodbc", "pyodbc"),
    "oracle": ("oracledb", "oracledb"),
    "clickhouse": ("clickhouse_connect", "clickhouse-connect"),
    "trino": ("trino", "trino"),
    "duckdb": ("duckdb", "duckdb"),
}


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def warehouse_driver_status(platform: str) -> dict[str, Any]:
    key = platform.casefold()
    if key not in _DRIVERS:
        return {
            "status": "UNSUPPORTED",
            "platform": platform,
            "supported": sorted(_DRIVERS),
        }
    module, package = _DRIVERS[key]
    return {
        "status": "PASS",
        "platform": key,
        "module": module,
        "package": package,
        "installed": importlib.util.find_spec(module) is not None,
    }


def install_warehouse_driver(
    platform: str,
    *,
    dry_run: bool = True,
    runner: Runner | None = None,
) -> dict[str, Any]:
    info = warehouse_driver_status(platform)
    if info["status"] != "PASS":
        return info
    if info["installed"]:
        return {**info, "action": "ALREADY_INSTALLED"}
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        str(info["package"]),
    ]
    if dry_run:
        return {
            **info,
            "action": "DRY_RUN",
            "command": command,
        }
    completed = (runner or _run)(command)
    return {
        **info,
        "action": "INSTALLED" if completed.returncode == 0 else "FAILED",
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "command": command,
    }
