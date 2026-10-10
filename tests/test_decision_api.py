from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_data_platform.api.decision import attach_decision_routes


def _client():
    app = attach_decision_routes(FastAPI())
    return TestClient(app)


def test_status_exposes_local_and_fail_closed_snowflake_states():
    response = _client().get("/api/v1/decision/status")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["evidence-overlap"]["available"] is True
    assert body["providers"]["snowflake-decision"]["available"] is False


def test_choice_endpoint_executes_bounded_local_decision():
    response = _client().post(
        "/api/v1/decision/choice",
        json={
            "payload": {"message": "payment retry failure"},
            "question": "route payment incident",
            "options": [
                {"key": "retry", "label": "Retry", "description": "payment failure"},
                {"key": "fraud", "label": "Fraud", "description": "suspicious activity"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choice_key"] == "retry"
    assert body["trace"]["provider"] == "evidence-overlap"


def test_choice_endpoint_can_abstain():
    response = _client().post(
        "/api/v1/decision/choice",
        json={
            "payload": {},
            "question": "route",
            "min_confidence": 0.99,
            "options": [
                {"key": "a", "label": "A"},
                {"key": "b", "label": "B"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["choice_key"] is None


def test_snowflake_endpoint_is_503_without_verified_executor():
    response = _client().post(
        "/api/v1/decision/truth",
        json={
            "provider": "snowflake-decision",
            "payload": {"status": "failed"},
            "statement": "pipeline failed",
        },
    )
    assert response.status_code == 503
    assert "private-preview" in response.json()["detail"]


def test_invalid_contract_is_400():
    response = _client().post(
        "/api/v1/decision/choice",
        json={
            "payload": {},
            "question": "route",
            "options": [{"key": "only", "label": "Only"}],
        },
    )
    assert response.status_code == 400
