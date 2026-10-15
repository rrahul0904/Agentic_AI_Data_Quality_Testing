from __future__ import annotations

import json
import re
from typing import Protocol

from .contracts import (
    ChoiceRequest,
    ChoiceResult,
    DecisionTrace,
    ScoreRequest,
    ScoreResult,
    TruthRequest,
    TruthResult,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(value: object) -> set[str]:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, sort_keys=True, default=str)
        except TypeError:
            text = str(value)
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _distribution(raw_scores: list[float], keys: list[str]) -> dict[str, float]:
    total = float(sum(raw_scores))
    return {key: score / total for key, score in zip(keys, raw_scores)}


class DecisionProvider(Protocol):
    name: str

    def choose(self, request: ChoiceRequest) -> ChoiceResult: ...

    def score(self, request: ScoreRequest) -> ScoreResult: ...

    def assess_truth(self, request: TruthRequest) -> TruthResult: ...


class EvidenceOverlapProvider:
    """Deterministic local baseline for smoke tests and offline operation.

    This is intentionally a simple lexical baseline, not a semantic-equivalence
    claim against Snowflake Decision or any LLM-backed decision model.
    """

    name = "evidence-overlap"

    def _source_tokens(self, payload: object, instruction: str) -> set[str]:
        return _tokens(payload) | _tokens(instruction)

    def choose(self, request: ChoiceRequest) -> ChoiceResult:
        source = self._source_tokens(request.payload, request.question)
        keys = [option.key for option in request.options]
        raw = []
        for option in request.options:
            evidence = _tokens(f"{option.key} {option.label} {option.description}")
            raw.append(1.0 + float(len(source & evidence)))
        probabilities = _distribution(raw, keys)
        selected = max(keys, key=lambda key: probabilities[key])
        return ChoiceResult(
            choice_key=selected,
            probabilities=probabilities,
            confidence=probabilities[selected],
            trace=DecisionTrace(provider=self.name, model="lexical-v1"),
        )

    def score(self, request: ScoreRequest) -> ScoreResult:
        source = self._source_tokens(request.payload, request.question)
        keys = [level.key for level in request.levels]
        raw = []
        for level in request.levels:
            evidence = _tokens(f"{level.key} {level.label} {level.description}")
            raw.append(1.0 + float(len(source & evidence)))
        probabilities = _distribution(raw, keys)
        score = sum(probabilities[level.key] * level.value for level in request.levels)
        return ScoreResult(
            score=score,
            probabilities=probabilities,
            confidence=max(probabilities.values()),
            trace=DecisionTrace(provider=self.name, model="lexical-v1"),
        )

    def assess_truth(self, request: TruthRequest) -> TruthResult:
        payload_tokens = _tokens(request.payload)
        statement_tokens = _tokens(request.statement)
        overlap = len(payload_tokens & statement_tokens)
        if not statement_tokens:
            probability_true = 0.5
        else:
            ratio = overlap / len(statement_tokens)
            probability_true = min(0.95, max(0.05, 0.25 + 0.70 * ratio))
        return TruthResult(
            probability_true=probability_true,
            confidence=max(probability_true, 1.0 - probability_true),
            trace=DecisionTrace(provider=self.name, model="lexical-v1"),
        )
