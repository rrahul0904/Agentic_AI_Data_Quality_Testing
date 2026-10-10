from __future__ import annotations

from dataclasses import replace

import pytest

from agentic_data_platform.decision import (
    ChoiceRequest,
    ChoiceResult,
    DecisionContractError,
    DecisionEngine,
    DecisionOption,
    DecisionPolicy,
    DecisionProviderError,
    DecisionProviderUnavailable,
    DecisionTrace,
    EvidenceOverlapProvider,
    RubricLevel,
    ScoreRequest,
    SnowflakeDecisionProvider,
    TruthRequest,
)


def _engine(*providers):
    return DecisionEngine(
        providers or (EvidenceOverlapProvider(),),
        default_provider=(providers[0].name if providers else "evidence-overlap"),
    )


def _choice(payload=None):
    return ChoiceRequest(
        payload=payload or {"message": "payment failure retry"},
        question="Route this payment incident",
        options=(
            DecisionOption("retry", "Retry payment", "transient payment failure"),
            DecisionOption("fraud", "Fraud review", "suspicious account activity"),
        ),
    )


def _score():
    return ScoreRequest(
        payload={"severity": "critical outage"},
        question="Score operational severity",
        levels=(
            RubricLevel("low", 1, "Low", "minor"),
            RubricLevel("medium", 2, "Medium", "degraded"),
            RubricLevel("critical", 3, "Critical", "outage"),
        ),
    )


def test_choice_is_bounded_and_distribution_is_valid():
    result = _engine().choose(_choice())
    assert result.choice_key == "retry"
    assert set(result.probabilities) == {"retry", "fraud"}
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.confidence == max(result.probabilities.values())


def test_score_is_probability_weighted_and_within_rubric():
    request = _score()
    result = _engine().score(request)
    expected = sum(result.probabilities[level.key] * level.value for level in request.levels)
    assert result.score == pytest.approx(expected)
    assert request.levels[0].value <= result.score <= request.levels[-1].value


def test_truth_probability_is_bounded():
    result = _engine().assess_truth(
        TruthRequest(payload={"status": "pipeline failed"}, statement="pipeline failed")
    )
    assert 0.0 <= result.probability_true <= 1.0
    assert 0.0 <= result.confidence <= 1.0


def test_threshold_can_abstain_without_fabricating_answer():
    result = _engine().choose(_choice(), policy=DecisionPolicy(min_confidence=0.99))
    assert result.abstained is True
    assert result.choice_key is None


def test_fallback_provider_is_recorded_and_can_satisfy_threshold():
    class HighConfidence:
        name = "high-confidence"

        def choose(self, request):
            return ChoiceResult(
                choice_key="fraud",
                probabilities={"retry": 0.05, "fraud": 0.95},
                confidence=0.95,
                trace=DecisionTrace(provider=self.name),
            )

        def score(self, request):
            raise AssertionError("unused")

        def assess_truth(self, request):
            raise AssertionError("unused")

    engine = DecisionEngine(
        (EvidenceOverlapProvider(), HighConfidence()),
        default_provider="evidence-overlap",
    )
    result = engine.choose(
        _choice(),
        policy=DecisionPolicy(min_confidence=0.9, fallback_provider="high-confidence"),
    )
    assert result.choice_key == "fraud"
    assert result.trace.provider == "high-confidence"
    assert result.trace.metadata["fallback_from"] == "evidence-overlap"


def test_batch_preserves_input_order():
    requests = [
        _choice({"message": "retry payment"}),
        _choice({"message": "fraud suspicious activity"}),
    ]
    results = _engine().choose_batch(requests)
    assert [result.choice_key for result in results] == ["retry", "fraud"]


def test_invalid_choice_contract_is_rejected_before_provider_call():
    with pytest.raises(DecisionContractError):
        ChoiceRequest(
            payload={},
            question="route",
            options=(DecisionOption("only", "Only"),),
        )


def test_invalid_provider_distribution_fails_closed():
    class BadProvider:
        name = "bad"

        def choose(self, request):
            return ChoiceResult(
                choice_key="retry",
                probabilities={"retry": 0.9, "fraud": 0.9},
                confidence=0.9,
                trace=DecisionTrace(provider=self.name),
            )

        def score(self, request):
            raise AssertionError("unused")

        def assess_truth(self, request):
            raise AssertionError("unused")

    with pytest.raises(DecisionProviderError):
        DecisionEngine((BadProvider(),), default_provider="bad").choose(_choice())


def test_score_provider_cannot_return_arbitrary_non_weighted_number():
    class BadScore(EvidenceOverlapProvider):
        name = "bad-score"

        def score(self, request):
            return replace(super().score(request), score=99.0)

    with pytest.raises(DecisionProviderError):
        DecisionEngine((BadScore(),), default_provider="bad-score").score(_score())


def test_snowflake_adapter_fails_closed_without_private_preview_executor():
    provider = SnowflakeDecisionProvider()
    with pytest.raises(DecisionProviderUnavailable, match="private-preview"):
        provider.choose(_choice())


def test_snowflake_adapter_uses_injected_canonical_executor_without_guessing_transport():
    calls = []

    def executor(operation, payload):
        calls.append((operation, payload))
        return {
            "choice_key": "fraud",
            "probabilities": {"retry": 0.1, "fraud": 0.9},
            "confidence": 0.9,
        }

    engine = DecisionEngine((SnowflakeDecisionProvider(executor),), default_provider="snowflake-decision")
    result = engine.choose(_choice())
    assert result.choice_key == "fraud"
    assert calls[0][0] == "choice"
    assert calls[0][1]["options"][0]["key"] == "retry"
