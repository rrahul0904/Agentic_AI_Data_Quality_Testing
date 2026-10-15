from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence


class DecisionContractError(ValueError):
    """Raised when a bounded-decision contract is malformed."""


class DecisionProviderError(RuntimeError):
    """Raised when a provider returns an invalid or unusable result."""


class DecisionProviderUnavailable(DecisionProviderError):
    """Raised when a configured provider cannot execute."""


def _require_nonempty(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not value:
        raise DecisionContractError(f"{field_name} must be non-empty")
    return value


def _validate_probability(value: float, field_name: str) -> float:
    value = float(value)
    if value < 0.0 or value > 1.0:
        raise DecisionProviderError(f"{field_name} must be between 0 and 1")
    return value


def validate_distribution(probabilities: Mapping[str, float], keys: Sequence[str]) -> dict[str, float]:
    expected = list(keys)
    if list(probabilities.keys()) != expected:
        raise DecisionProviderError(
            f"probability keys must match declared order {expected!r}; got {list(probabilities.keys())!r}"
        )
    validated = {key: _validate_probability(probabilities[key], f"probabilities[{key!r}]") for key in expected}
    total = sum(validated.values())
    if abs(total - 1.0) > 1e-6:
        raise DecisionProviderError(f"probabilities must sum to 1.0; got {total:.12f}")
    return validated


@dataclass(frozen=True)
class DecisionOption:
    key: str
    label: str
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _require_nonempty(self.key, "option.key"))
        object.__setattr__(self, "label", _require_nonempty(self.label, "option.label"))


@dataclass(frozen=True)
class RubricLevel:
    key: str
    value: float
    label: str
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _require_nonempty(self.key, "level.key"))
        object.__setattr__(self, "label", _require_nonempty(self.label, "level.label"))
        object.__setattr__(self, "value", float(self.value))


@dataclass(frozen=True)
class ChoiceRequest:
    payload: Any
    question: str
    options: tuple[DecisionOption, ...]
    request_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "question", _require_nonempty(self.question, "question"))
        object.__setattr__(self, "options", tuple(self.options))
        if len(self.options) < 2:
            raise DecisionContractError("choice requires at least two options")
        keys = [option.key for option in self.options]
        if len(keys) != len(set(keys)):
            raise DecisionContractError("choice option keys must be unique")


@dataclass(frozen=True)
class ScoreRequest:
    payload: Any
    question: str
    levels: tuple[RubricLevel, ...]
    request_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "question", _require_nonempty(self.question, "question"))
        object.__setattr__(self, "levels", tuple(self.levels))
        if len(self.levels) < 2:
            raise DecisionContractError("score requires at least two ordered levels")
        keys = [level.key for level in self.levels]
        if len(keys) != len(set(keys)):
            raise DecisionContractError("score level keys must be unique")
        values = [level.value for level in self.levels]
        if any(right <= left for left, right in zip(values, values[1:])):
            raise DecisionContractError("score level values must be strictly increasing in declared order")


@dataclass(frozen=True)
class TruthRequest:
    payload: Any
    statement: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", _require_nonempty(self.statement, "statement"))


@dataclass(frozen=True)
class DecisionPolicy:
    min_confidence: float = 0.0
    fallback_provider: str | None = None
    abstain_below_threshold: bool = True

    def __post_init__(self) -> None:
        value = float(self.min_confidence)
        if value < 0.0 or value > 1.0:
            raise DecisionContractError("min_confidence must be between 0 and 1")
        object.__setattr__(self, "min_confidence", value)


@dataclass(frozen=True)
class DecisionTrace:
    provider: str
    model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _require_nonempty(self.provider, "trace.provider"))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def with_metadata(self, **updates: Any) -> "DecisionTrace":
        merged = dict(self.metadata)
        merged.update(updates)
        return replace(self, metadata=merged)


@dataclass(frozen=True)
class ChoiceResult:
    choice_key: str | None
    probabilities: Mapping[str, float]
    confidence: float
    trace: DecisionTrace
    abstained: bool = False


@dataclass(frozen=True)
class ScoreResult:
    score: float | None
    probabilities: Mapping[str, float]
    confidence: float
    trace: DecisionTrace
    abstained: bool = False


@dataclass(frozen=True)
class TruthResult:
    probability_true: float | None
    confidence: float
    trace: DecisionTrace
    abstained: bool = False
