from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .contracts import (
    ChoiceRequest,
    ChoiceResult,
    DecisionProviderError,
    DecisionProviderUnavailable,
    DecisionTrace,
    ScoreRequest,
    ScoreResult,
    TruthRequest,
    TruthResult,
)

CanonicalExecutor = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class SnowflakeDecisionProvider:
    """Clean-room Snowflake Decision adapter boundary.

    Snowflake Decision is private preview. This adapter deliberately does not
    invent an undocumented SQL/request payload. A caller must inject an executor
    that translates the canonical request to the account-specific Snowflake
    invocation and returns the normalized canonical result documented here.
    """

    name = "snowflake-decision"

    def __init__(self, executor: CanonicalExecutor | None = None, model: str = "snowflake-decision") -> None:
        self._executor = executor
        self._model = model

    def _run(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._executor is None:
            raise DecisionProviderUnavailable(
                "Snowflake Decision executor is not configured; private-preview transport is unavailable"
            )
        result = self._executor(operation, payload)
        if not isinstance(result, Mapping):
            raise DecisionProviderError("Snowflake Decision executor must return a mapping")
        return result

    def choose(self, request: ChoiceRequest) -> ChoiceResult:
        canonical_request = {
            "payload": request.payload,
            "question": request.question,
            "options": [
                {"key": option.key, "label": option.label, "description": option.description}
                for option in request.options
            ],
            "request_id": request.request_id,
        }
        result = self._run("choice", canonical_request)
        return ChoiceResult(
            choice_key=result.get("choice_key"),
            probabilities=dict(result.get("probabilities", {})),
            confidence=float(result.get("confidence", 0.0)),
            trace=DecisionTrace(provider=self.name, model=self._model),
        )

    def score(self, request: ScoreRequest) -> ScoreResult:
        canonical_request = {
            "payload": request.payload,
            "question": request.question,
            "levels": [
                {
                    "key": level.key,
                    "value": level.value,
                    "label": level.label,
                    "description": level.description,
                }
                for level in request.levels
            ],
            "request_id": request.request_id,
        }
        result = self._run("score", canonical_request)
        return ScoreResult(
            score=float(result["score"]) if result.get("score") is not None else None,
            probabilities=dict(result.get("probabilities", {})),
            confidence=float(result.get("confidence", 0.0)),
            trace=DecisionTrace(provider=self.name, model=self._model),
        )

    def assess_truth(self, request: TruthRequest) -> TruthResult:
        canonical_request = {
            "payload": request.payload,
            "statement": request.statement,
            "request_id": request.request_id,
        }
        result = self._run("truth", canonical_request)
        probability = result.get("probability_true")
        probability_true = float(probability) if probability is not None else None
        confidence = result.get("confidence")
        if confidence is None and probability_true is not None:
            confidence = max(probability_true, 1.0 - probability_true)
        return TruthResult(
            probability_true=probability_true,
            confidence=float(confidence or 0.0),
            trace=DecisionTrace(provider=self.name, model=self._model),
        )
