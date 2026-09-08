from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app


def test_runtime_session_replay_api_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    client = TestClient(create_app())
    response = client.get("/api/v1/runtime-sessions")
    assert response.status_code == 200
    assert "sessions" in response.json()
