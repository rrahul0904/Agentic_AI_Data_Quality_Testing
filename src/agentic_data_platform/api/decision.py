from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException

from agentic_data_platform.decision import (
    ChoiceRequest,
    DecisionContractError,
    DecisionEngine,
    DecisionOption,
    DecisionPolicy,
    DecisionProviderError,
    DecisionProviderUnavailable,
    EvidenceOverlapProvider,
    RubricLevel,
    ScoreRequest,
    SnowflakeDecisionProvider,
    TruthRequest,
)

DECISION_PATHS = frozenset(
    {
        "/api/v1/decision/status",
        "/api/v1/decision/choice",
        "/api/v1/decision/score",
        "/api/v1/decision/truth",
    }
)


def _engine(provider: str) -> DecisionEngine:
    if provider == "evidence-overlap":
        instance = EvidenceOverlapProvider()
    elif provider == "snowflake-decision":
        instance = SnowflakeDecisionProvider()
    else:
        raise HTTPException(status_code=400, detail=f"unknown decision provider: {provider}")
    return DecisionEngine((instance,), default_provider=instance.name)


def _policy(body: dict[str, Any]) -> DecisionPolicy:
    return DecisionPolicy(
        min_confidence=float(body.get("min_confidence", 0.0)),
        abstain_below_threshold=bool(body.get("abstain_below_threshold", True)),
    )


def _call(operation):
    try:
        return asdict(operation())
    except DecisionProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (DecisionContractError, DecisionProviderError, TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def decision_status() -> dict[str, Any]:
    return {
        "status": "PASS",
        "capability": "bounded-decision",
        "operations": ["choice", "score", "truth"],
        "providers": {
            "evidence-overlap": {"available": True, "kind": "deterministic-local-baseline"},
            "snowflake-decision": {
                "available": False,
                "kind": "private-preview-adapter",
                "reason": "verified account executor is not configured",
            },
        },
    }


def decision_choice(body: dict[str, Any]) -> dict[str, Any]:
    def execute():
        provider = str(body.get("provider") or "evidence-overlap")
        options = tuple(
            DecisionOption(
                key=str(item["key"]),
                label=str(item.get("label") or item["key"]),
                description=str(item.get("description") or ""),
            )
            for item in body["options"]
        )
        request = ChoiceRequest(
            payload=body.get("payload"),
            question=str(body["question"]),
            options=options,
            request_id=body.get("request_id"),
        )
        return _engine(provider).choose(request, policy=_policy(body))

    return _call(execute)


def decision_score(body: dict[str, Any]) -> dict[str, Any]:
    def execute():
        provider = str(body.get("provider") or "evidence-overlap")
        levels = tuple(
            RubricLevel(
                key=str(item["key"]),
                value=float(item["value"]),
                label=str(item.get("label") or item["key"]),
                description=str(item.get("description") or ""),
            )
            for item in body["levels"]
        )
        request = ScoreRequest(
            payload=body.get("payload"),
            question=str(body["question"]),
            levels=levels,
            request_id=body.get("request_id"),
        )
        return _engine(provider).score(request, policy=_policy(body))

    return _call(execute)


def decision_truth(body: dict[str, Any]) -> dict[str, Any]:
    def execute():
        provider = str(body.get("provider") or "evidence-overlap")
        request = TruthRequest(
            payload=body.get("payload"),
            statement=str(body["statement"]),
            request_id=body.get("request_id"),
        )
        return _engine(provider).assess_truth(request, policy=_policy(body))

    return _call(execute)


def attach_decision_routes(application: FastAPI) -> FastAPI:
    existing = {getattr(route, "path", None) for route in application.routes}
    definitions = (
        ("/api/v1/decision/status", decision_status, ["GET"], "decision_status"),
        ("/api/v1/decision/choice", decision_choice, ["POST"], "decision_choice"),
        ("/api/v1/decision/score", decision_score, ["POST"], "decision_score"),
        ("/api/v1/decision/truth", decision_truth, ["POST"], "decision_truth"),
    )
    for path, endpoint, methods, name in definitions:
        if path not in existing:
            application.add_api_route(path, endpoint, methods=methods, tags=["decision"], name=name)
    return application
