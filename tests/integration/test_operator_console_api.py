from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app


def test_operator_console_contract_uses_real_api_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.setenv("ADE_DATABASE_PATH", str(tmp_path / "control.db"))
    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    tools = client.get("/api/v1/tools")
    assert domains.status_code == 200
    assert tools.status_code == 200
    assert len(tools.json()) >= 285
