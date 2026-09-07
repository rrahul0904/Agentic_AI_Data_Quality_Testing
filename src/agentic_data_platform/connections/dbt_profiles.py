"""dbt profiles.yml discovery with credential redaction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_SENSITIVE = (
    "password",
    "pass",
    "token",
    "secret",
    "private_key",
    "private-key",
    "api_key",
    "apikey",
)


def _sensitive(key: str) -> bool:
    value = key.casefold()
    return any(token in value for token in _SENSITIVE)


def resolve_profiles_path(
    *,
    explicit: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_dir = os.getenv("DBT_PROFILES_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser() / "profiles.yml")
    if project_dir:
        candidates.append(Path(project_dir).expanduser() / "profiles.yml")
    candidates.append(Path.home() / ".dbt" / "profiles.yml")
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def discover_dbt_profiles(
    *,
    path: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> dict[str, Any]:
    source = resolve_profiles_path(explicit=path, project_dir=project_dir)
    if source is None:
        return {
            "status": "PASS",
            "path": None,
            "connection_count": 0,
            "connections": [],
        }
    payload = yaml.safe_load(source.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError("dbt profiles.yml must contain a mapping")

    connections = []
    for profile_name, profile in payload.items():
        if not isinstance(profile, dict):
            continue
        outputs = profile.get("outputs") or {}
        if not isinstance(outputs, dict):
            continue
        target = profile.get("target")
        for output_name, config in outputs.items():
            if not isinstance(config, dict):
                continue
            redacted = {
                str(key): ("****" if _sensitive(str(key)) else value)
                for key, value in config.items()
            }
            connections.append(
                {
                    "profile": str(profile_name),
                    "output": str(output_name),
                    "target": bool(target == output_name),
                    "name": f"{profile_name}:{output_name}",
                    "type": str(config.get("type") or "unknown"),
                    "config": redacted,
                }
            )
    return {
        "status": "PASS",
        "path": str(source),
        "connection_count": len(connections),
        "connections": sorted(
            connections,
            key=lambda item: (item["profile"], item["output"]),
        ),
    }
