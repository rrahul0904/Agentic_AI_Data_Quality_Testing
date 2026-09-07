"""Shared scale and dirty-data configuration."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SEED = 20260906


@dataclass(frozen=True)
class ScaleConfig:
    properties: int
    guests: int
    reservations: int
    events: int
    chunk_size: int


SCALES = {
    # CI-friendly while retaining cross-domain relationships.
    "small": ScaleConfig(10, 5_000, 50_000, 500_000, 25_000),
    "medium": ScaleConfig(100, 100_000, 1_000_000, 10_000_000, 100_000),
    "large": ScaleConfig(500, 1_000_000, 10_000_000, 100_000_000, 250_000),
}

BAD_RECORD_RATE = 0.001
DUPLICATE_RATE = 0.002
LATE_ARRIVAL_RATE = 0.01


def get_scale(name: str) -> ScaleConfig:
    try:
        return SCALES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown scale {name!r}; choose from {', '.join(SCALES)}") from exc

