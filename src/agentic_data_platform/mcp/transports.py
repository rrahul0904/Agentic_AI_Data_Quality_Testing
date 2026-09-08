from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import McpServerConfig


class McpTransport(ABC):
    @abstractmethod
    def request(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def close(self) -> None:
        return None


class HttpMcpTransport(McpTransport):
    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._client = httpx.Client(timeout=config.timeout_seconds, headers=config.headers)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.url:
            raise ValueError("MCP HTTP URL missing")
        response = self._client.post(self.config.url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("MCP response must be a JSON object")
        return data

    def close(self) -> None:
        self._client.close()


class StdioMcpTransport(McpTransport):
    def __init__(self, config: McpServerConfig) -> None:
        if not config.command:
            raise ValueError("MCP stdio command missing")
        env = dict(config.environment)
        import os
        merged = os.environ.copy()
        merged.update(env)
        self._process = subprocess.Popen(
            list(config.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=merged,
        )

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP stdio transport is closed")
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read(1000) if self._process.stderr else ""
            raise RuntimeError(f"MCP stdio server closed unexpectedly: {stderr.strip()}")
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError("MCP response must be a JSON object")
        return data

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
