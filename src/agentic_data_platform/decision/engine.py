from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .contracts import (
    ChoiceRequest,
    ChoiceResult,
    DecisionPolicy,
    DecisionProviderError,
    ScoreRequest,
    ScoreResult,
    TruthRequest,
    TruthResult,
    validate_distribution,
)
from .providers import DecisionProvider


class DecisionEngine:
    def __init__(self, providers: Iterable[DecisionProvider], default_provider: str) -> None:
        self._providers = {provider.name: provider for provider in providers}
        if default_provider not in self._providers:
            raise DecisionProviderError(f"default provider {default_provider!r} is not registered")
        self._default_provider = default_provider

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(self._providers.keys())

    def _provider(self, name: str | None) -> DecisionProvider:
        resolved = name or self._default_provider
        try:
            return self._providers[resolved]
        except KeyError as exc:
            raise DecisionProviderError(f"provider {resolved!r} is not registered") from exc

    def _validate_choice(self, request: ChoiceRequest, result: ChoiceResult) -> ChoiceResult:
        keys = [option.key for option in request.options]
        probabilities = validate_distribution(result.probabilities, keys)
        confidence = float(result.confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise DecisionProviderError("choice confidence must be between 0 and 1")
        if result.choice_key not in keys:
            raise DecisionProviderError("choice_key must be one of the declared options")
        return replace(result, probabilities=probabilities, confidence=confidence)

    def _validate_score(self, request: ScoreRequest, result: ScoreResult) -> ScoreResult:
        keys = [level.key for level in request.levels]
        probabilities = validate_distribution(result.probabilities, keys)
        confidence = float(result.confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise DecisionProviderError("score confidence must be between 0 and 1")
        if result.score is None:
            raise DecisionProviderError("score provider returned no score")
        score = float(result.score)
        low, high = request.levels[0].value, request.levels[-1].value
        if score < low - 1e-9 or score > high + 1e-9:
            raise DecisionProviderError(f"score must be within rubric range [{low}, {high}]")
        expected = sum(probabilities[level.key] * level.value for level in request.levels)
        if abs(score - expected) > 1e-6:
            raise DecisionProviderError("score must equal the probability-weighted rubric value")
        return replace(result, probabilities=probabilities, confidence=confidence, score=score)

    def _validate_truth(self, result: TruthResult) -> TruthResult:
        if result.probability_true is None:
            raise DecisionProviderError("truth provider returned no probability_true")
        probability = float(result.probability_true)
        confidence = float(result.confidence)
        if probability < 0.0 or probability > 1.0:
            raise DecisionProviderError("probability_true must be between 0 and 1")
        if confidence < 0.0 or confidence > 1.0:
            raise DecisionProviderError("truth confidence must be between 0 and 1")
        return replace(result, probability_true=probability, confidence=confidence)

    def _apply_policy(self, result, policy: DecisionPolicy, operation, request):
        if result.confidence >= policy.min_confidence:
            return result
        if policy.fallback_provider and result.trace.provider != policy.fallback_provider:
            fallback = self._provider(policy.fallback_provider)
            fallback_result = operation(fallback, request)
            fallback_result = replace(
                fallback_result,
                trace=fallback_result.trace.with_metadata(fallback_from=result.trace.provider),
            )
            if fallback_result.confidence >= policy.min_confidence:
                return fallback_result
            result = fallback_result
        if policy.abstain_below_threshold:
            if isinstance(result, ChoiceResult):
                return replace(result, choice_key=None, abstained=True)
            if isinstance(result, ScoreResult):
                return replace(result, score=None, abstained=True)
            if isinstance(result, TruthResult):
                return replace(result, probability_true=None, abstained=True)
        return result

    def choose(
        self,
        request: ChoiceRequest,
        *,
        provider: str | None = None,
        policy: DecisionPolicy | None = None,
    ) -> ChoiceResult:
        selected = self._provider(provider)

        def operation(p: DecisionProvider, r: ChoiceRequest) -> ChoiceResult:
            return self._validate_choice(r, p.choose(r))

        result = operation(selected, request)
        return self._apply_policy(result, policy or DecisionPolicy(), operation, request)

    def score(
        self,
        request: ScoreRequest,
        *,
        provider: str | None = None,
        policy: DecisionPolicy | None = None,
    ) -> ScoreResult:
        selected = self._provider(provider)

        def operation(p: DecisionProvider, r: ScoreRequest) -> ScoreResult:
            return self._validate_score(r, p.score(r))

        result = operation(selected, request)
        return self._apply_policy(result, policy or DecisionPolicy(), operation, request)

    def assess_truth(
        self,
        request: TruthRequest,
        *,
        provider: str | None = None,
        policy: DecisionPolicy | None = None,
    ) -> TruthResult:
        selected = self._provider(provider)

        def operation(p: DecisionProvider, r: TruthRequest) -> TruthResult:
            return self._validate_truth(p.assess_truth(r))

        result = operation(selected, request)
        return self._apply_policy(result, policy or DecisionPolicy(), operation, request)

    def choose_batch(self, requests: Iterable[ChoiceRequest], **kwargs) -> list[ChoiceResult]:
        return [self.choose(request, **kwargs) for request in requests]

    def score_batch(self, requests: Iterable[ScoreRequest], **kwargs) -> list[ScoreResult]:
        return [self.score(request, **kwargs) for request in requests]

    def truth_batch(self, requests: Iterable[TruthRequest], **kwargs) -> list[TruthResult]:
        return [self.assess_truth(request, **kwargs) for request in requests]
