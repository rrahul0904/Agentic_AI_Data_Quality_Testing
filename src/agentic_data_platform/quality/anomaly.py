"""Deterministic proactive anomaly detection for technically-green pipelines."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean, pstdev
from typing import Any, Iterable


@dataclass(frozen=True)
class AnomalyFinding:
    metric: str
    status: str
    observed: float
    baseline: float | None
    threshold: float
    deviation: float
    reason: str

    def public(self) -> dict[str, Any]:
        return asdict(self)


def relative_change(
    metric: str,
    observed: float,
    baseline: float,
    *,
    threshold_pct: float,
) -> AnomalyFinding:
    if threshold_pct < 0:
        raise ValueError("threshold_pct must be non-negative")
    if baseline == 0:
        deviation_pct = 0.0 if observed == 0 else 100.0
    else:
        deviation_pct = (observed - baseline) / abs(baseline) * 100
    anomalous = abs(deviation_pct) >= threshold_pct
    return AnomalyFinding(
        metric,
        "ANOMALY" if anomalous else "PASS",
        float(observed),
        float(baseline),
        float(threshold_pct),
        float(deviation_pct),
        f"relative change {deviation_pct:.2f}% {'exceeds' if anomalous else 'within'} {threshold_pct:.2f}% threshold",
    )


def absolute_threshold(
    metric: str,
    observed: float,
    *,
    maximum: float,
) -> AnomalyFinding:
    anomalous = observed > maximum
    return AnomalyFinding(
        metric,
        "ANOMALY" if anomalous else "PASS",
        float(observed),
        None,
        float(maximum),
        float(observed - maximum),
        f"{metric}={observed} {'exceeds' if anomalous else 'within'} maximum {maximum}",
    )


def ratio_deviation(
    metric: str,
    numerator: float,
    denominator: float,
    historical_ratio: float,
    *,
    tolerance: float,
) -> AnomalyFinding:
    current = numerator / denominator if denominator else 0.0
    deviation = current - historical_ratio
    anomalous = abs(deviation) >= tolerance
    return AnomalyFinding(
        metric,
        "ANOMALY" if anomalous else "PASS",
        float(current),
        float(historical_ratio),
        float(tolerance),
        float(deviation),
        f"ratio deviation {deviation:.4f} {'exceeds' if anomalous else 'within'} tolerance {tolerance:.4f}",
    )


def historical_zscore(
    metric: str,
    observed: float,
    history: Iterable[float],
    *,
    z_threshold: float = 3.0,
) -> AnomalyFinding:
    values = [float(item) for item in history]
    if len(values) < 2:
        return AnomalyFinding(
            metric, "INSUFFICIENT_HISTORY", float(observed),
            mean(values) if values else None, float(z_threshold), 0.0,
            "at least two historical observations are required",
        )
    baseline = mean(values)
    deviation_std = pstdev(values)
    zscore = 0.0 if deviation_std == 0 and observed == baseline else (
        float("inf") if deviation_std == 0 else (observed - baseline) / deviation_std
    )
    anomalous = abs(zscore) >= z_threshold
    return AnomalyFinding(
        metric,
        "ANOMALY" if anomalous else "PASS",
        float(observed),
        float(baseline),
        float(z_threshold),
        float(zscore),
        f"z-score {zscore:.3f} {'exceeds' if anomalous else 'within'} threshold {z_threshold:.3f}",
    )


def detect_pipeline_anomalies(signals: dict[str, Any]) -> dict[str, Any]:
    """Evaluate supported signals without using an LLM.

    Supported signal keys cover volume, freshness, null/duplicate rates,
    source-target ratios, business ratios, watermark lag and historical
    deviation.
    """
    findings: list[AnomalyFinding] = []

    if signals.get("observed_volume") is not None and signals.get("historical_volume") is not None:
        findings.append(relative_change(
            "volume",
            float(signals["observed_volume"]),
            float(signals["historical_volume"]),
            threshold_pct=float(signals.get("volume_threshold_pct", 15)),
        ))

    if signals.get("freshness_lag_minutes") is not None and signals.get("freshness_sla_minutes") is not None:
        findings.append(absolute_threshold(
            "freshness_lag_minutes",
            float(signals["freshness_lag_minutes"]),
            maximum=float(signals["freshness_sla_minutes"]),
        ))

    if signals.get("current_null_pct") is not None and signals.get("historical_null_pct") is not None:
        findings.append(relative_change(
            "null_percentage",
            float(signals["current_null_pct"]),
            float(signals["historical_null_pct"]),
            threshold_pct=float(signals.get("null_change_threshold_pct", 100)),
        ))

    if signals.get("current_duplicate_pct") is not None:
        findings.append(absolute_threshold(
            "duplicate_percentage",
            float(signals["current_duplicate_pct"]),
            maximum=float(signals.get("duplicate_max_pct", 0)),
        ))

    if signals.get("source_count") is not None and signals.get("target_count") is not None:
        source = float(signals["source_count"])
        target = float(signals["target_count"])
        current_ratio = target / source if source else 1.0
        findings.append(AnomalyFinding(
            "source_target_ratio",
            "ANOMALY" if abs(1.0 - current_ratio) > float(signals.get("source_target_ratio_tolerance", 0)) else "PASS",
            current_ratio,
            1.0,
            float(signals.get("source_target_ratio_tolerance", 0)),
            current_ratio - 1.0,
            "target/source completeness ratio",
        ))

    if (
        signals.get("payment_count") is not None
        and signals.get("reservation_count") is not None
        and signals.get("historical_payment_to_reservation_ratio") is not None
    ):
        findings.append(ratio_deviation(
            "payment_to_reservation_ratio",
            float(signals["payment_count"]),
            float(signals["reservation_count"]),
            float(signals["historical_payment_to_reservation_ratio"]),
            tolerance=float(signals.get("ratio_tolerance", 0.1)),
        ))
    elif (
        signals.get("payment_to_reservation_ratio") is not None
        and signals.get("historical_payment_to_reservation_ratio") is not None
    ):
        observed = float(signals["payment_to_reservation_ratio"])
        baseline = float(signals["historical_payment_to_reservation_ratio"])
        findings.append(AnomalyFinding(
            "payment_to_reservation_ratio",
            "ANOMALY" if abs(observed - baseline) >= float(signals.get("ratio_tolerance", 0.1)) else "PASS",
            observed,
            baseline,
            float(signals.get("ratio_tolerance", 0.1)),
            observed - baseline,
            "business ratio deviation",
        ))

    if signals.get("watermark_lag_minutes") is not None:
        findings.append(absolute_threshold(
            "watermark_lag_minutes",
            float(signals["watermark_lag_minutes"]),
            maximum=float(signals.get("watermark_sla_minutes", 30)),
        ))

    if signals.get("historical_values") is not None and signals.get("observed_value") is not None:
        findings.append(historical_zscore(
            str(signals.get("historical_metric", "historical_deviation")),
            float(signals["observed_value"]),
            signals["historical_values"],
            z_threshold=float(signals.get("z_threshold", 3.0)),
        ))

    anomalies = [item for item in findings if item.status == "ANOMALY"]
    return {
        "status": "ANOMALY" if anomalies else "PASS",
        "anomaly_count": len(anomalies),
        "finding_count": len(findings),
        "findings": [item.public() for item in findings],
        "technical_state": {
            "airflow": signals.get("airflow_state"),
            "dbt": signals.get("dbt_state"),
        },
    }
