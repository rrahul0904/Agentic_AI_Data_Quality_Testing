from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments while preserving comment markers inside strings."""
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _read_json_config(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if path.suffix == ".jsonc":
        text = _strip_jsonc(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"refusing to read malformed MCP config: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"MCP config root must be an object: {path}")
    return value



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
        data = _read_json_config(source)
        raw = data.get("mcp") or data.get("mcpServers") or {}
        return {name: McpServerConfig.from_dict(name, item) for name, item in raw.items() if isinstance(item, dict)}

    @staticmethod
    def add(path: str | Path, name: str, config: Mapping[str, Any]) -> Path:
        target = Path(path)
        data: dict[str, Any] = {}
        if target.exists():
            data = _read_json_config(target)
        data.setdefault("mcp", {})[name] = dict(config)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2) + "\n")
        return target

    @staticmethod
    def remove(path: str | Path, name: str) -> bool:
        target = Path(path)
        if not target.exists():
            return False
        data = _read_json_config(target)
        servers = data.get("mcp") or {}
        if name not in servers:
            return False
        del servers[name]
        target.write_text(json.dumps(data, indent=2) + "\n")
        return True


    @staticmethod
    def set_enabled(path: str | Path, name: str, enabled: bool) -> Path:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"MCP config not found: {target}")
        data = _read_json_config(target)
        servers = data.get("mcp") or data.get("mcpServers")
        if not isinstance(servers, dict) or name not in servers:
            raise KeyError(f"MCP server not found: {name}")
        server = servers[name]
        if not isinstance(server, dict):
            raise ValueError(f"MCP server config must be an object: {name}")
        server["enabled"] = bool(enabled)
        target.write_text(json.dumps(data, indent=2) + "\n")
        return target
