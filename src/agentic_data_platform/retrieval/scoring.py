"""Explainable metadata scoring profiles for ADE Search."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class NumericBoost:
    field: str
    weight: float = 1.0
    minimum: float | None = None
    maximum: float | None = None

    def score(self, metadata: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
        raw = metadata.get(self.field)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.0, {"field": self.field, "status": "MISSING_OR_NON_NUMERIC"}
        if not math.isfinite(value):
            return 0.0, {"field": self.field, "status": "NON_FINITE"}
        if self.minimum is not None and self.maximum is not None:
            if self.maximum <= self.minimum:
                raise ValueError("numeric boost maximum must be greater than minimum")
            normalized = (value - self.minimum) / (self.maximum - self.minimum)
            normalized = max(0.0, min(1.0, normalized))
            mode = "min_max"
        else:
            normalized = 0.5 + math.atan(value) / math.pi
            mode = "atan"
        return normalized, {
            "field": self.field,
            "status": "PASS",
            "raw": value,
            "normalized": normalized,
            "mode": mode,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class TimeDecay:
    field: str
    half_life_seconds: float
    weight: float = 1.0

    def score(
        self,
        metadata: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> tuple[float, dict[str, Any]]:
        if self.half_life_seconds <= 0:
            raise ValueError("time decay half_life_seconds must be positive")
        raw = metadata.get(self.field)
        if raw is None:
            return 0.0, {"field": self.field, "status": "MISSING"}
        if isinstance(raw, datetime):
            timestamp = raw
        else:
            try:
                timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                return 0.0, {"field": self.field, "status": "INVALID_TIMESTAMP", "raw": str(raw)}
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (reference - timestamp.astimezone(reference.tzinfo)).total_seconds())
        decay = 0.5 ** (age_seconds / self.half_life_seconds)
        return decay, {
            "field": self.field,
            "status": "PASS",
            "timestamp": timestamp.isoformat(),
            "age_seconds": age_seconds,
            "half_life_seconds": self.half_life_seconds,
            "decay": decay,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class ScoringProfile:
    numeric_boosts: Sequence[NumericBoost] = field(default_factory=tuple)
    time_decays: Sequence[TimeDecay] = field(default_factory=tuple)

    def score(
        self,
        metadata: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> tuple[float, dict[str, Any]]:
        components: list[tuple[float, float]] = []
        evidence: dict[str, Any] = {"numeric_boosts": [], "time_decays": []}
        for boost in self.numeric_boosts:
            if boost.weight < 0:
                raise ValueError("numeric boost weight must be non-negative")
            score, detail = boost.score(metadata)
            components.append((score, boost.weight))
            evidence["numeric_boosts"].append(detail)
        for decay in self.time_decays:
            if decay.weight < 0:
                raise ValueError("time decay weight must be non-negative")
            score, detail = decay.score(metadata, now=now)
            components.append((score, decay.weight))
            evidence["time_decays"].append(detail)
        total_weight = sum(weight for _, weight in components)
        score = (
            sum(value * weight for value, weight in components) / total_weight
            if total_weight
            else 0.0
        )
        evidence["score"] = score
        evidence["component_weight"] = total_weight
        return score, evidence
