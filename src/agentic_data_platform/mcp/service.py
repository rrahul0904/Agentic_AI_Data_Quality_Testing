"""MCP catalog, discovery, auth references and OAuth state handling."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

from agentic_data_platform.mcp.config import McpConfigStore, McpServerConfig


@dataclass(frozen=True)
class McpCatalogEntry:
    name: str
    description: str
    config: dict[str, Any]
    source: str = "builtin"


class McpCatalog:
    def __init__(self, entries: Iterable[McpCatalogEntry] = ()) -> None:
        self._entries = {entry.name: entry for entry in entries}

    @classmethod
    def builtin(cls) -> "McpCatalog":
        return cls(
            [
                McpCatalogEntry(
                    "filesystem",
                    "Local filesystem MCP server",
                    {
                        "type": "local",
                        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
                    },
                ),
                McpCatalogEntry(
                    "github",
                    "GitHub MCP server via environment token",
                    {
                        "type": "local",
                        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
                        "environment": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"},
                    },
                ),
            ]
        )

    def list(self) -> list[dict[str, Any]]:
        return [asdict(self._entries[name]) for name in sorted(self._entries)]

    def get(self, name: str) -> McpCatalogEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(f"MCP catalog entry not found: {name}") from exc

    def install(self, name: str, path: str | Path, *, server_name: str | None = None) -> Path:
        entry = self.get(name)
        return McpConfigStore.add(path, server_name or name, entry.config)


class McpDiscovery:
    """Discover MCP configs from this project and common agent clients."""

    CANDIDATES = (
        ".altimate-code/altimate-code.json",
        ".opencode/opencode.json",
        ".opencode/opencode.jsonc",
        ".cursor/mcp.json",
        ".vscode/mcp.json",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".mcp.json",
    )

    @classmethod
    def discover(cls, root: str | Path) -> dict[str, Any]:
        base = Path(root).expanduser().resolve()
        configs = []
        servers: dict[str, list[dict[str, Any]]] = {}
        for relative in cls.CANDIDATES:
            path = base / relative
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text())
            except json.JSONDecodeError:
                configs.append({"path": str(path), "status": "MALFORMED"})
                continue
            configs.append({"path": str(path), "status": "PASS"})
            container = raw.get("mcp") or raw.get("mcpServers") or raw.get("servers") or {}
            if not isinstance(container, Mapping):
                continue
            for name, item in container.items():
                if isinstance(item, Mapping):
                    servers.setdefault(str(name), []).append(
                        {
                            "path": str(path),
                            "config": dict(item),
                        }
                    )
        return {
            "root": str(base),
            "configs": configs,
            "servers": servers,
            "server_count": len(servers),
        }


class McpAuthStore:
    """Persist only references to auth environment variables, never secret values."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_auth (
              server_name TEXT PRIMARY KEY,
              method TEXT NOT NULL,
              token_env TEXT,
              metadata_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def set_env_token(
        self,
        server_name: str,
        env_name: str,
        *,
        method: str = "bearer",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not env_name or not env_name.replace("_", "").isalnum():
            raise ValueError("invalid MCP auth environment variable")
        self.connection.execute(
            """
            INSERT INTO mcp_auth VALUES (?, ?, ?, ?)
            ON CONFLICT(server_name) DO UPDATE SET
              method=excluded.method,
              token_env=excluded.token_env,
              metadata_json=excluded.metadata_json
            """,
            (server_name, method, env_name, json.dumps(dict(metadata or {}), sort_keys=True)),
        )
        self.connection.commit()
        return self.status(server_name)

    def remove(self, server_name: str) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM mcp_auth WHERE server_name = ?",
            (server_name,),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def status(self, server_name: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM mcp_auth WHERE server_name = ?",
            (server_name,),
        ).fetchone()
        if row is None:
            return {"server_name": server_name, "configured": False}
        env_name = row["token_env"]
        return {
            "server_name": server_name,
            "configured": True,
            "method": row["method"],
            "token_env": env_name,
            "credential_available": bool(os.getenv(env_name)) if env_name else False,
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    def headers(self, server_name: str) -> dict[str, str]:
        row = self.connection.execute(
            "SELECT * FROM mcp_auth WHERE server_name = ?",
            (server_name,),
        ).fetchone()
        if row is None:
            return {}
        env_name = row["token_env"]
        value = os.getenv(env_name) if env_name else None
        if not value:
            return {}
        method = str(row["method"]).casefold()
        if method == "bearer":
            return {"Authorization": f"Bearer {value}"}
        if method == "api-key":
            header = json.loads(row["metadata_json"] or "{}").get("header", "X-API-Key")
            return {str(header): value}
        return {"Authorization": value}


@dataclass(frozen=True)
class OAuthPending:
    server_name: str
    state: str
    verifier: str
    challenge: str
    authorize_url: str
    token_url: str | None
    redirect_uri: str
    client_id: str
    scope: str | None = None


class McpOAuthManager:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_oauth_pending (
              state TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def _pkce() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(48)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return verifier, challenge

    def begin(
        self,
        server_name: str,
        *,
        authorize_url: str,
        client_id: str,
        redirect_uri: str,
        token_url: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        state = secrets.token_urlsafe(24)
        verifier, challenge = self._pkce()
        pending = OAuthPending(
            server_name,
            state,
            verifier,
            challenge,
            authorize_url,
            token_url,
            redirect_uri,
            client_id,
            scope,
        )
        self.connection.execute(
            "INSERT INTO mcp_oauth_pending VALUES (?, ?)",
            (state, json.dumps(asdict(pending), sort_keys=True)),
        )
        self.connection.commit()
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if scope:
            params["scope"] = scope
        return {
            "server_name": server_name,
            "authorization_url": authorize_url
            + ("&" if "?" in authorize_url else "?")
            + urlencode(params),
            "state": state,
            "method": "code",
        }

    def callback(self, *, state: str, code: str | None, error: str | None = None) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT payload_json FROM mcp_oauth_pending WHERE state = ?",
            (state,),
        ).fetchone()
        if row is None:
            raise KeyError("unknown or expired MCP OAuth state")
        self.connection.execute("DELETE FROM mcp_oauth_pending WHERE state = ?", (state,))
        self.connection.commit()
        pending = OAuthPending(**json.loads(row["payload_json"]))
        if error:
            return {
                "status": "FAIL",
                "server_name": pending.server_name,
                "error": error,
            }
        if not code:
            raise ValueError("OAuth authorization code is required")
        return {
            "status": "PENDING_TOKEN_EXCHANGE",
            "server_name": pending.server_name,
            "code": code,
            "code_verifier": pending.verifier,
            "token_url": pending.token_url,
            "redirect_uri": pending.redirect_uri,
            "client_id": pending.client_id,
        }


def configured_servers(path: str | Path) -> dict[str, Any]:
    configs = McpConfigStore.load(path)
    return {
        "path": str(Path(path)),
        "servers": [
            {
                "name": name,
                "transport": config.transport,
                "enabled": config.enabled,
                "url": config.url,
                "command": list(config.command),
                "unresolved_env": list(config.unresolved_env),
                "oauth": bool(config.oauth),
            }
            for name, config in sorted(configs.items())
        ],
    }


def merge_auth(config: McpServerConfig, headers: Mapping[str, str]) -> McpServerConfig:
    return McpServerConfig(
        name=config.name,
        transport=config.transport,
        command=config.command,
        url=config.url,
        environment=dict(config.environment),
        headers={**config.headers, **dict(headers)},
        timeout_seconds=config.timeout_seconds,
        enabled=config.enabled,
        oauth=config.oauth,
        unresolved_env=config.unresolved_env,
    )
