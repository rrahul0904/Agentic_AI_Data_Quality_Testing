"""Governed Snowflake-managed dbt execution."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from agentic_data_platform.connectors._common import identifier
from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.snowflake.governed_mutation import (
    GovernedSnowflakeMutationExecutor,
    plan_snowflake_mutation,
)


_SUPPORTED_COMMANDS = frozenset({
    "build",
    "compile",
    "deps",
    "docs generate",
    "list",
    "parse",
    "run",
    "run-operation",
    "seed",
    "show",
    "snapshot",
    "test",
})
_BLOCKED_FLAGS = frozenset({
    "--state",
    "--target-path",
    "--log-path",
    "--profiles-dir",
    "--project-dir",
    "--log-format",
    "--log-format-file",
})
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_NAME = re.compile(r"(?i)(SECRET|PASSWORD|TOKEN|PRIVATE|CREDENTIAL|API_KEY|ACCESS_KEY)")


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _qualified_identifier(value: str) -> str:
    parts = [item.strip() for item in str(value).split(".") if item.strip()]
    if not parts:
        raise ValueError("dbt project object name is required")
    return ".".join(identifier(item) for item in parts)


def _workspace_identifier(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        raise ValueError("workspace_name is required")
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise ValueError("workspace_name contains invalid control characters")
    escaped = raw.replace('"', '""')
    return f'user$.public."{escaped}"'


def _project_root(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    path = PurePosixPath(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("project_root must be a workspace-relative subdirectory")
    return path.as_posix()


def _args(command: str, flags: Iterable[str]) -> str:
    normalized = str(command or "").strip().casefold()
    if normalized not in _SUPPORTED_COMMANDS:
        raise ValueError(f"unsupported Snowflake-managed dbt command: {command}")
    values = [str(item) for item in flags]
    for item in values:
        if any(character in item for character in ("\x00", "\n", "\r")):
            raise ValueError("dbt flags may not contain control characters")
    for index, item in enumerate(values):
        flag_name = item.split("=", 1)[0].casefold()
        if flag_name in _BLOCKED_FLAGS:
            raise ValueError(f"Snowflake-managed dbt does not support flag: {item}")
        if index and values[index - 1].casefold() in _BLOCKED_FLAGS:
            raise ValueError(f"Snowflake-managed dbt does not support flag: {values[index - 1]}")
    return " ".join([normalized, *values]).strip()


def render_managed_dbt_sql(
    *,
    project_name: str | None = None,
    workspace_name: str | None = None,
    command: str = "run",
    flags: Iterable[str] = (),
    dbt_version: str | None = None,
    dbt_environment: str | None = None,
    env_vars: dict[str, str] | None = None,
    external_access_integrations: Iterable[str] = (),
    project_root: str | None = None,
    if_exists: bool = False,
) -> str:
    if bool(project_name) == bool(workspace_name):
        raise ValueError("specify exactly one of project_name or workspace_name")

    args_value = _args(command, flags)
    statement = "EXECUTE DBT PROJECT"
    if if_exists:
        statement += " IF EXISTS"

    if workspace_name:
        statement += f" FROM WORKSPACE {_workspace_identifier(workspace_name)}"
    else:
        statement += f" {_qualified_identifier(str(project_name))}"

    statement += f" ARGS = {_literal(args_value)}"

    if dbt_version:
        version = str(dbt_version).strip()
        if not re.fullmatch(r"[A-Za-z0-9._+-]+", version):
            raise ValueError("invalid dbt_version")
        statement += f" DBT_VERSION = {_literal(version)}"

    if external_access_integrations:
        integrations = ", ".join(
            identifier(str(item).strip()) for item in external_access_integrations
        )
        statement += f" EXTERNAL_ACCESS_INTEGRATIONS = ({integrations})"

    if dbt_environment:
        statement += f" ENVIRONMENT = {_literal(str(dbt_environment))}"

    if env_vars:
        rendered = []
        for key, value in sorted(env_vars.items()):
            name = str(key)
            if not _ENV_NAME.fullmatch(name):
                raise ValueError(f"invalid dbt environment variable name: {name}")
            if _SECRET_NAME.search(name):
                raise ValueError(
                    f"sensitive dbt environment variable must use Snowflake secret/env.yml handling instead of inline ENV_VARS: {name}"
                )
            rendered.append(f"{_literal(name)} = {_literal(str(value))}")
        statement += " ENV_VARS = (" + ", ".join(rendered) + ")"

    root = _project_root(project_root)
    if root is not None:
        if not workspace_name:
            raise ValueError("PROJECT_ROOT is supported only for workspace execution")
        statement += f" PROJECT_ROOT = {_literal(root)}"

    return statement


def plan_managed_dbt(
    *,
    ade_environment: str = "dev",
    **kwargs: Any,
) -> dict[str, Any]:
    sql = render_managed_dbt_sql(**kwargs)
    plan = plan_snowflake_mutation(sql, environment=ade_environment)
    return {
        **plan,
        "mode": "SNOWFLAKE_MANAGED_DBT_PLAN",
        "managed_dbt": {
            "command": kwargs.get("command", "run"),
            "project_name": kwargs.get("project_name"),
            "workspace_name": kwargs.get("workspace_name"),
            "project_root": kwargs.get("project_root"),
            "dbt_version": kwargs.get("dbt_version"),
            "dbt_environment": kwargs.get("dbt_environment"),
            "external_access_integrations": list(kwargs.get("external_access_integrations") or ()),
            "env_var_names": sorted((kwargs.get("env_vars") or {}).keys()),
        },
    }


class ManagedDbtExecutor:
    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("ManagedDbtExecutor requires SnowflakeConnector")
        self.executor = GovernedSnowflakeMutationExecutor(connector)

    def execute(
        self,
        *,
        approval_fingerprint: str,
        approved: bool,
        ade_environment: str = "dev",
        dry_run: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        sql = render_managed_dbt_sql(**kwargs)
        result = self.executor.execute(
            sql,
            environment=ade_environment,
            approval_fingerprint=approval_fingerprint,
            approved=approved,
            confirm_destructive=False,
            dry_run=dry_run,
        )
        return {
            **result,
            "managed_dbt": {
                "command": kwargs.get("command", "run"),
                "project_name": kwargs.get("project_name"),
                "workspace_name": kwargs.get("workspace_name"),
                "project_root": kwargs.get("project_root"),
            },
        }


def supported_managed_dbt_commands() -> dict[str, Any]:
    return {
        "status": "PASS",
        "commands": sorted(_SUPPORTED_COMMANDS),
        "blocked_flags": sorted(_BLOCKED_FLAGS),
    }
