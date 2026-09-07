"""Secret-safe persistent connection profiles and deterministic discovery."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from agentic_data_platform.models import utc_now


_SECRET_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "oauth",
    "credential",
)
_ENV_REF = re.compile(r"^\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}$")
_DBT_ENV = re.compile(r"\{\{\s*env_var\(['\"]([^'\"]+)['\"](?:\s*,\s*['\"][^'\"]*['\"])?\)\s*\}\}")


def is_secret_key(key: str) -> bool:
    lowered = key.casefold()
    return any(part in lowered for part in _SECRET_PARTS)


def redact(value: Any, key: str | None = None) -> Any:
    if key and is_secret_key(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def _validate_config(config: dict[str, Any]) -> None:
    def walk(value: Any, key: str | None = None) -> None:
        if key and is_secret_key(key) and value not in (None, "", "<redacted>"):
            if not isinstance(value, str) or _ENV_REF.fullmatch(value) is None:
                raise ValueError(
                    f"secret field {key!r} must use an environment reference like ${{ENV:VARIABLE}}"
                )
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)
    walk(config)


class ConnectionStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS connection_profiles (
              name TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              config_json TEXT NOT NULL,
              source TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connection_settings (
              key TEXT PRIMARY KEY,
              value TEXT
            );
            """
        )
        self.connection.commit()

    def add(
        self,
        name: str,
        platform: str,
        config: dict[str, Any] | None = None,
        *,
        source: str = "manual",
        replace: bool = False,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        clean_platform = platform.strip().casefold()
        if not clean_name or not clean_platform:
            raise ValueError("connection name and platform are required")
        payload = dict(config or {})
        _validate_config(payload)
        now = utc_now()
        if replace:
            self.connection.execute(
                """
                INSERT INTO connection_profiles VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  platform=excluded.platform,
                  config_json=excluded.config_json,
                  source=excluded.source,
                  updated_at=excluded.updated_at
                """,
                (clean_name, clean_platform, json.dumps(payload, sort_keys=True), source, now, now),
            )
        else:
            self.connection.execute(
                "INSERT INTO connection_profiles VALUES (?, ?, ?, ?, ?, ?)",
                (clean_name, clean_platform, json.dumps(payload, sort_keys=True), source, now, now),
            )
        self.connection.commit()
        return self.show(clean_name)

    def remove(self, name: str) -> bool:
        cursor = self.connection.execute("DELETE FROM connection_profiles WHERE name = ?", (name,))
        self.connection.execute(
            "UPDATE connection_settings SET value = NULL WHERE key = 'default' AND value = ?",
            (name,),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def _decode(self, row: sqlite3.Row) -> dict[str, Any]:
        config = json.loads(row["config_json"] or "{}")
        return {
            "name": row["name"],
            "platform": row["platform"],
            "config": redact(config),
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_default": self.default() == row["name"],
        }

    def show(self, name: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM connection_profiles WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise KeyError(f"connection not found: {name}")
        return self._decode(row)

    def raw(self, name: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM connection_profiles WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise KeyError(f"connection not found: {name}")
        return {
            "name": row["name"],
            "platform": row["platform"],
            "config": json.loads(row["config_json"] or "{}"),
            "source": row["source"],
        }

    def list(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM connection_profiles ORDER BY name"
        ).fetchall()
        return [self._decode(row) for row in rows]

    def set_default(self, name: str | None) -> str | None:
        if name is not None:
            self.show(name)
        self.connection.execute(
            """
            INSERT INTO connection_settings(key, value) VALUES ('default', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (name,),
        )
        self.connection.commit()
        return name

    def default(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM connection_settings WHERE key = 'default'"
        ).fetchone()
        return str(row["value"]) if row and row["value"] else None

    def resolve_config(self, name: str) -> dict[str, Any]:
        profile = self.raw(name)

        def resolve(value: Any) -> Any:
            if isinstance(value, str):
                match = _ENV_REF.fullmatch(value)
                if match:
                    return os.getenv(match.group(1))
                return value
            if isinstance(value, dict):
                return {key: resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            return value

        return {
            "name": profile["name"],
            "platform": profile["platform"],
            "config": resolve(profile["config"]),
            "source": profile["source"],
        }

    def discover_environment(self) -> list[dict[str, Any]]:
        definitions = {
            "snowflake": ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER"),
            "bigquery": ("ADE_BIGQUERY_PROJECT",),
            "databricks": ("ADE_DATABRICKS_HOST", "ADE_DATABRICKS_HTTP_PATH"),
            "postgres": ("ADE_POSTGRES_DSN",),
            "redshift": ("ADE_REDSHIFT_DSN",),
            "mysql": ("ADE_MYSQL_HOST", "ADE_MYSQL_USER", "ADE_MYSQL_DATABASE"),
            "sqlserver": ("ADE_SQLSERVER_CONNECTION_STRING",),
            "oracle": ("ADE_ORACLE_DSN", "ADE_ORACLE_USER"),
            "clickhouse": ("ADE_CLICKHOUSE_HOST",),
            "trino": ("ADE_TRINO_HOST", "ADE_TRINO_USER", "ADE_TRINO_CATALOG"),
        }
        found = []
        for platform, variables in definitions.items():
            present = [name for name in variables if os.getenv(name)]
            if len(present) != len(variables):
                continue
            found.append(
                {
                    "name": f"env-{platform}",
                    "platform": platform,
                    "source": "environment",
                    "variables": list(variables),
                    "secrets_redacted": True,
                }
            )
        return found

    def discover_dbt_profiles(self, path: str | Path) -> list[dict[str, Any]]:
        profile_path = Path(path).expanduser()
        if not profile_path.is_file():
            return []
        text = _DBT_ENV.sub(lambda match: f"${{ENV:{match.group(1)}}}", profile_path.read_text())
        parsed = yaml.safe_load(text) or {}
        found = []
        for profile_name, profile in parsed.items():
            if not isinstance(profile, dict):
                continue
            outputs = profile.get("outputs") or {}
            for target_name, target in outputs.items():
                if not isinstance(target, dict) or not target.get("type"):
                    continue
                found.append(
                    {
                        "name": f"dbt-{profile_name}-{target_name}",
                        "platform": str(target["type"]).casefold(),
                        "source": str(profile_path),
                        "profile": profile_name,
                        "target": target_name,
                        "config": redact(target),
                    }
                )
        return found

    def discover(self, *, dbt_profiles: str | Path | None = None) -> dict[str, Any]:
        profile_path = (
            Path(dbt_profiles).expanduser()
            if dbt_profiles
            else Path.home() / ".dbt" / "profiles.yml"
        )
        return {
            "environment": self.discover_environment(),
            "dbt_profiles": self.discover_dbt_profiles(profile_path),
        }
