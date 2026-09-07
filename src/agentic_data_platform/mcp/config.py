from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_env(value: str) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        raw = os.getenv(name)
        if raw is None:
            missing.append(name)
            return ""
        return raw

    return _ENV.sub(replace, value), sorted(set(missing))


def resolve_mapping(values: Mapping[str, Any] | None) -> tuple[dict[str, str], list[str]]:
    output: dict[str, str] = {}
    missing: list[str] = []
    for key, raw in (values or {}).items():
        if not isinstance(raw, str):
            continue
        value, unresolved = resolve_env(raw)
        output[str(key)] = value
        missing.extend(unresolved)
    return output, sorted(set(missing))


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str
    command: tuple[str, ...] = ()
    url: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    enabled: bool = True
    oauth: dict[str, str] | bool | None = None
    unresolved_env: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "McpServerConfig":
        transport = str(data.get("type") or ("remote" if data.get("url") else "local")).casefold()
        command = data.get("command") or ()
        if isinstance(command, str):
            command = (command,)
        environment, env_missing = resolve_mapping(data.get("environment") or data.get("env"))
        headers, header_missing = resolve_mapping(data.get("headers"))
        url = str(data["url"]) if data.get("url") else None
        if transport in {"local", "stdio"} and not command:
            raise ValueError(f"MCP server {name} requires command")
        if transport in {"remote", "http", "sse", "streamable-http"} and not url:
            raise ValueError(f"MCP server {name} requires url")
        return cls(
            name=name,
            transport="stdio" if transport in {"local", "stdio"} else "http",
            command=tuple(str(item) for item in command),
            url=url,
            environment=environment,
            headers=headers,
            timeout_seconds=float(data.get("timeout", 30.0)),
            enabled=bool(data.get("enabled", True)),
            oauth=data.get("oauth"),
            unresolved_env=tuple(sorted(set(env_missing + header_missing))),
        )


class McpConfigStore:
    FILENAMES = ("altimate-code.json", "opencode.json", "opencode.jsonc")

    @classmethod
    def resolve_path(cls, base: str | Path, *, global_config: bool = False) -> Path:
        root = Path(base).expanduser().resolve()
        candidates: list[Path] = []
        if not global_config:
            for subdir in (".altimate-code", ".opencode"):
                candidates.extend(root / subdir / name for name in cls.FILENAMES)
        candidates.extend(root / name for name in cls.FILENAMES)
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    @staticmethod
    def load(path: str | Path) -> dict[str, McpServerConfig]:
        source = Path(path)
        if not source.exists():
            return {}
        text = source.read_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"refusing to read malformed MCP config: {source}") from exc
        raw = data.get("mcp") or data.get("mcpServers") or {}
        return {name: McpServerConfig.from_dict(name, item) for name, item in raw.items() if isinstance(item, dict)}

    @staticmethod
    def add(path: str | Path, name: str, config: Mapping[str, Any]) -> Path:
        target = Path(path)
        data: dict[str, Any] = {}
        if target.exists():
            try:
                data = json.loads(target.read_text())
            except json.JSONDecodeError as exc:
                raise ValueError(f"refusing to overwrite malformed MCP config: {target}") from exc
        data.setdefault("mcp", {})[name] = dict(config)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2) + "\n")
        return target

    @staticmethod
    def remove(path: str | Path, name: str) -> bool:
        target = Path(path)
        if not target.exists():
            return False
        try:
            data = json.loads(target.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"refusing to overwrite malformed MCP config: {target}") from exc
        servers = data.get("mcp") or {}
        if name not in servers:
            return False
        del servers[name]
        target.write_text(json.dumps(data, indent=2) + "\n")
        return True
