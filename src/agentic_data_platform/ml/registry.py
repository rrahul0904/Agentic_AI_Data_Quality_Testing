"""Snowpark ML / Snowflake Model Registry integration."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from agentic_data_platform.connectors._common import identifier
from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.snowflake.governed_mutation import plan_snowflake_mutation


def _qualified(value: str) -> str:
    parts = [part.strip() for part in str(value).split(".") if part.strip()]
    if not parts:
        raise ValueError("model identifier is required")
    return ".".join(identifier(part) for part in parts)


def _version(value: str) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$-]*", text):
        raise ValueError("invalid model version identifier")
    return text


class SnowflakeModelRegistryAdapter:
    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("SnowflakeModelRegistryAdapter requires SnowflakeConnector")
        self.connector = connector

    def models(self, *, database: str | None = None, schema: str | None = None) -> list[dict[str, Any]]:
        sql = "SHOW MODELS"
        if schema:
            target = f"{database}.{schema}" if database else schema
            sql += f" IN SCHEMA {_qualified(target)}"
        elif database:
            sql += f" IN DATABASE {identifier(database)}"
        return [dict(row) for row in self.connector.execute_read(sql).rows]

    def versions(self, model_name: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connector.execute_read(
                f"SHOW VERSIONS IN MODEL {_qualified(model_name)}"
            ).rows
        ]


def plan_model_lifecycle(
    *,
    action: str,
    model_name: str,
    version_name: str | None = None,
    environment: str = "dev",
) -> dict[str, Any]:
    action = str(action).casefold()
    model = _qualified(model_name)
    if action == "set-default":
        if not version_name:
            raise ValueError("set-default requires version_name")
        sql = f"ALTER MODEL {model} SET DEFAULT_VERSION = '{_version(version_name)}'"
    elif action == "drop-version":
        if not version_name:
            raise ValueError("drop-version requires version_name")
        sql = f"ALTER MODEL {model} DROP VERSION {_version(version_name)}"
    elif action == "drop-model":
        sql = f"DROP MODEL {model}"
    else:
        raise ValueError("model lifecycle action must be set-default, drop-version, or drop-model")
    return {
        **plan_snowflake_mutation(sql, environment=environment),
        "mode": "SNOWPARK_MODEL_LIFECYCLE_PLAN",
        "action": action,
        "model_name": model,
        "version_name": version_name,
        "sql": sql,
    }


def plan_log_model(
    *,
    model_name: str,
    version_name: str,
    comment: str | None = None,
    metrics: dict[str, Any] | None = None,
    conda_dependencies: list[str] | None = None,
    pip_requirements: list[str] | None = None,
    python_version: str | None = None,
) -> dict[str, Any]:
    model = identifier(model_name)
    version = _version(version_name)
    payload = {
        "model_name": model,
        "version_name": version,
        "comment": comment,
        "metrics": metrics or {},
        "conda_dependencies": conda_dependencies or [],
        "pip_requirements": pip_requirements or [],
        "python_version": python_version,
    }
    fingerprint = sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    code = (
        "from snowflake.ml.registry import Registry\n\n"
        "# session and model must already exist in the calling Python process.\n"
        "registry = Registry(session=session)\n"
        "model_version = registry.log_model(\n"
        "    model=model,\n"
        f"    model_name={model!r},\n"
        f"    version_name={version!r},\n"
        f"    comment={comment!r},\n"
        f"    metrics={metrics or {}!r},\n"
        f"    conda_dependencies={conda_dependencies or []!r},\n"
        f"    pip_requirements={pip_requirements or []!r},\n"
        f"    python_version={python_version!r},\n"
        ")\n"
    )
    return {
        "status": "PASS",
        "mode": "SNOWPARK_MODEL_LOG_PLAN",
        "approval_fingerprint": fingerprint,
        "parameters": payload,
        "python": code,
    }


class EmbeddedModelRegistryRuntime:
    """Library integration for processes that already hold a Snowpark session/model object."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def log_model(self, model_object: Any, plan: dict[str, Any], *, approval_fingerprint: str) -> dict[str, Any]:
        if approval_fingerprint != plan.get("approval_fingerprint"):
            return {"status": "BLOCKED_APPROVAL", "reason": "model log plan fingerprint mismatch"}
        params = dict(plan["parameters"])
        result = self.registry.log_model(
            model=model_object,
            model_name=params["model_name"],
            version_name=params["version_name"],
            comment=params["comment"],
            metrics=params["metrics"],
            conda_dependencies=params["conda_dependencies"],
            pip_requirements=params["pip_requirements"],
            python_version=params["python_version"],
        )
        return {
            "status": "PASS",
            "model_name": params["model_name"],
            "version_name": params["version_name"],
            "result": str(result),
        }
