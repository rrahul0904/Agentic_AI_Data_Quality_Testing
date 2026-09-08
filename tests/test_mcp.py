from __future__ import annotations

import pytest

from agentic_data_platform.mcp import McpClient, McpConfigStore, McpManager, McpServerConfig, McpTransport


class FixtureTransport(McpTransport):
    def __init__(self):
        self.calls = []
        self.closed = False

    def request(self, payload):
        self.calls.append(payload)
        method = payload["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]}
        elif method == "resources/list":
            result = {"resources": [{"uri": "file:///fixture", "name": "fixture"}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": payload["params"]["arguments"].get("value", "")}]}
        else:
            return {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32601, "message": "unknown"}}
        return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

    def close(self):
        self.closed = True


def test_mcp_client_initialize_discover_and_call():
    transport = FixtureTransport()
    config = McpServerConfig(name="fixture", transport="http", url="https://example.invalid")
    client = McpClient(config, transport=transport)
    assert client.connect().status == "connected"
    assert client.tools()[0]["name"] == "echo"
    assert client.resources()[0]["uri"] == "file:///fixture"
    result = client.call_tool("echo", {"value": "hello"})
    assert result["content"][0]["text"] == "hello"
    client.close()
    assert transport.closed is True


def test_mcp_env_resolution_and_unresolved_failure(monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "secret-value")
    config = McpServerConfig.from_dict(
        "remote",
        {
            "type": "remote",
            "url": "https://example.invalid/mcp",
            "headers": {"Authorization": "Bearer ${MCP_TOKEN}", "X-Missing": "${NOT_DEFINED}"},
        },
    )
    assert config.headers["Authorization"] == "Bearer secret-value"
    assert config.headers["X-Missing"] == ""
    assert config.unresolved_env == ("NOT_DEFINED",)
    client = McpClient(config, transport=FixtureTransport())
    status = client.connect()
    assert status.status == "failed"
    assert "NOT_DEFINED" in status.error


def test_mcp_config_store_refuses_malformed_file(tmp_path):
    path = tmp_path / ".altimate-code" / "altimate-code.json"
    path.parent.mkdir()
    path.write_text("{ broken")
    with pytest.raises(ValueError):
        McpConfigStore.add(path, "fixture", {"type": "remote", "url": "https://example.invalid"})


def test_mcp_config_add_load_remove(tmp_path):
    path = tmp_path / ".altimate-code" / "altimate-code.json"
    McpConfigStore.add(path, "fixture", {"type": "remote", "url": "https://example.invalid", "enabled": True})
    loaded = McpConfigStore.load(path)
    assert loaded["fixture"].transport == "http"
    assert McpConfigStore.remove(path, "fixture") is True
    assert McpConfigStore.load(path) == {}


def test_mcp_manager_tracks_status_and_removal():
    transports = {}

    def factory(config):
        transport = FixtureTransport()
        transports[config.name] = transport
        return McpClient(config, transport=transport)

    manager = McpManager(factory=factory)
    status = manager.add(McpServerConfig(name="one", transport="http", url="https://example.invalid"))
    assert status.status == "connected"
    assert manager.status()["one"]["status"] == "connected"
    assert manager.remove("one") is True
    assert transports["one"].closed is True
