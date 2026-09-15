from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentic_data_platform.retrieval import NumericBoost, ScoringProfile, TimeDecay


def test_numeric_boost_is_bounded_and_explainable():
    profile = ScoringProfile(
        numeric_boosts=(NumericBoost("quality", weight=2.0, minimum=0.0, maximum=100.0),)
    )
    score, evidence = profile.score({"quality": 80})
    assert score == 0.8
    assert evidence["numeric_boosts"][0]["mode"] == "min_max"
    assert evidence["numeric_boosts"][0]["raw"] == 80.0


def test_time_decay_uses_explicit_half_life_without_future_penalty():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    profile = ScoringProfile(
        time_decays=(TimeDecay("updated_at", half_life_seconds=3600.0),)
    )
    score, evidence = profile.score(
        {"updated_at": (now - timedelta(hours=1)).isoformat()},
        now=now,
    )
    assert round(score, 8) == 0.5
    assert evidence["time_decays"][0]["age_seconds"] == 3600.0

    future_score, _ = profile.score(
        {"updated_at": (now + timedelta(hours=1)).isoformat()},
        now=now,
    )
    assert future_score == 1.0
