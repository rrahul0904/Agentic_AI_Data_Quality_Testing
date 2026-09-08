from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import McpServerConfig
from .transports import HttpMcpTransport, McpTransport, StdioMcpTransport


@dataclass(frozen=True)
class McpStatus:
    status: str
    error: str | None = None


class McpClient:
    def __init__(self, config: McpServerConfig, transport: McpTransport | None = None) -> None:
        self.config = config
        self.transport = transport or (
            StdioMcpTransport(config) if config.transport == "stdio" else HttpMcpTransport(config)
        )
        self._next_id = 1
        self.status = McpStatus("disabled" if not config.enabled else "disconnected")

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = self.transport.request(payload)
        if response.get("id") not in {None, request_id}:
            raise RuntimeError("MCP response id mismatch")
        if "error" in response:
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"MCP {method} failed: {message}")
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP {method} returned invalid result")
        return result

    def connect(self) -> McpStatus:
        if not self.config.enabled:
            self.status = McpStatus("disabled")
            return self.status
        if self.config.unresolved_env:
            self.status = McpStatus(
                "failed",
                "unresolved environment variables: " + ", ".join(self.config.unresolved_env),
            )
            return self.status
        try:
            self._call(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"roots": {}},
                    "clientInfo": {"name": "agentic-data-engineering-os", "version": "0.4.0"},
                },
            )
            self.status = McpStatus("connected")
        except Exception as exc:
            self.status = McpStatus("failed", str(exc))
        return self.status

    def tools(self) -> list[dict[str, Any]]:
        self._require_connected()
        result = self._call("tools/list", {})
        return list(result.get("tools", []))

    def resources(self) -> list[dict[str, Any]]:
        self._require_connected()
        result = self._call("resources/list", {})
        return list(result.get("resources", []))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_connected()
        return self._call("tools/call", {"name": name, "arguments": arguments or {}})

    def reconnect(self) -> McpStatus:
        self.close()
        return self.connect()

    def close(self) -> None:
        self.transport.close()
        self.status = McpStatus("disconnected")

    def _require_connected(self) -> None:
        if self.status.status != "connected":
            raise RuntimeError(f"MCP server {self.config.name} is not connected: {self.status.error or self.status.status}")


class McpManager:
    def __init__(self, factory: Callable[[McpServerConfig], McpClient] | None = None) -> None:
        self._factory = factory or McpClient
        self._clients: dict[str, McpClient] = {}

    def add(self, config: McpServerConfig) -> McpStatus:
        if config.name in self._clients:
            self._clients[config.name].close()
        client = self._factory(config)
        self._clients[config.name] = client
        return client.connect()

    def remove(self, name: str) -> bool:
        client = self._clients.pop(name, None)
        if client is None:
            return False
        client.close()
        return True

    def status(self) -> dict[str, dict[str, str | None]]:
        return {
            name: {"status": client.status.status, "error": client.status.error}
            for name, client in sorted(self._clients.items())
        }

    def get(self, name: str) -> McpClient:
        try:
            return self._clients[name]
        except KeyError as exc:
            raise KeyError(f"MCP server not found: {name}") from exc
