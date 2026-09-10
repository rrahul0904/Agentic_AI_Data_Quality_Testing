from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

import agentic_data_platform.api as api_package


def _routes(application):
    return [
        (getattr(route, "path", None), method)
        for route in application.routes
        for method in (getattr(route, "methods", set()) or set())
    ]


def test_knowledge_routes_and_agent_route_are_composed_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    application = api_package.create_app()
    routes = _routes(application)
    assert routes.count(("/api/v1/knowledge/status", "GET")) == 1
    assert routes.count(("/api/v1/knowledge/search", "GET")) == 1
    assert routes.count(("/api/v1/knowledge/index-project", "POST")) == 1
    assert routes.count(("/api/v1/knowledge/ingest-text", "POST")) == 1
    assert routes.count(("/api/v1/knowledge/upload", "POST")) == 1
    assert routes.count(("/api/v1/agent/query", "POST")) == 1
    assert routes.count(("/api/v1/certification/coco", "GET")) == 1


def test_knowledge_ingest_search_and_live_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ADE_AGENT_PROVIDER", "openai")
    client = TestClient(api_package.create_app())

    ingest = client.post(
        "/api/v1/knowledge/ingest-text",
        json={
            "source": "business-rules",
            "text": "Reservation refunds reduce recognized room revenue.",
            "metadata": {"approved": True},
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["status"] == "INDEXED"

    search = client.get("/api/v1/knowledge/search", params={"query": "refunds room revenue"})
    assert search.status_code == 200
    assert search.json()["results"]

    blocked = client.post(
        "/api/v1/agent/query",
        json={"question": "Investigate revenue", "mode": "live"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "BLOCKED_EXTERNAL"


def test_api_package_reload_preserves_certification_and_knowledge_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    reloaded = importlib.reload(api_package)
    reloaded = importlib.reload(reloaded)
    application = reloaded.create_app()
    routes = _routes(application)
    assert routes.count(("/api/v1/certification/coco", "GET")) == 1
    assert routes.count(("/api/v1/knowledge/status", "GET")) == 1
    assert routes.count(("/api/v1/agent/query", "POST")) == 1
