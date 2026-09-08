from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from agentic_data_platform.mcp import (
    McpAuthStore,
    McpCatalog,
    McpConfigStore,
    McpDiscovery,
    McpOAuthManager,
)


def test_mcp_jsonc_load_and_enable_disable(tmp_path):
    path = tmp_path / ".opencode" / "opencode.jsonc"
    path.parent.mkdir(parents=True)
    path.write_text(
        """
        {
          // comment
          "mcp": {
            "remote": {
              "type": "remote",
              "url": "https://example.invalid/mcp",
              "enabled": true
            }
          }
        }
        """
    )
    loaded = McpConfigStore.load(path)
    assert loaded["remote"].enabled is True
    McpConfigStore.set_enabled(path, "remote", False)
    loaded = McpConfigStore.load(path)
    assert loaded["remote"].enabled is False


def test_mcp_catalog_install_and_discovery(tmp_path):
    config_path = tmp_path / ".altimate-code" / "altimate-code.json"
    catalog = McpCatalog.builtin()
    assert {"filesystem", "github"}.issubset({item["name"] for item in catalog.list()})
    catalog.install("filesystem", config_path)
    loaded = McpConfigStore.load(config_path)
    assert loaded["filesystem"].transport == "stdio"

    cursor = tmp_path / ".cursor" / "mcp.json"
    cursor.parent.mkdir()
    cursor.write_text(
        '{"mcpServers":{"warehouse":{"type":"remote","url":"https://example.invalid"}}}'
    )
    found = McpDiscovery.discover(tmp_path)
    assert "warehouse" in found["servers"]
    assert found["server_count"] >= 1


def test_mcp_auth_store_persists_only_environment_reference(tmp_path, monkeypatch):
    database = tmp_path / "mcp-auth.db"
    store = McpAuthStore(database)
    status = store.set_env_token("warehouse", "MCP_WAREHOUSE_TOKEN")
    assert status["configured"] is True
    assert status["credential_available"] is False

    monkeypatch.setenv("MCP_WAREHOUSE_TOKEN", "secret-token")
    status = store.status("warehouse")
    assert status["credential_available"] is True
    assert "secret-token" not in str(status)
    assert store.headers("warehouse") == {"Authorization": "Bearer secret-token"}

    raw = database.read_bytes()
    assert b"secret-token" not in raw


def test_mcp_oauth_pkce_state_and_callback_are_validated():
    manager = McpOAuthManager()
    started = manager.begin(
        "remote",
        authorize_url="https://auth.example/authorize",
        token_url="https://auth.example/token",
        client_id="client",
        redirect_uri="http://127.0.0.1:8765/callback",
        scope="mcp.read mcp.write",
    )
    parsed = urlparse(started["authorization_url"])
    query = parse_qs(parsed.query)
    assert query["state"][0] == started["state"]
    assert query["code_challenge_method"][0] == "S256"
    assert query["code_challenge"][0]

    callback = manager.callback(state=started["state"], code="authorization-code")
    assert callback["status"] == "PENDING_TOKEN_EXCHANGE"
    assert callback["code"] == "authorization-code"
    assert callback["code_verifier"]

    try:
        manager.callback(state=started["state"], code="replay")
    except KeyError:
        pass
    else:
        raise AssertionError("OAuth state replay must fail")
