from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agentic_data_platform.quality.anomaly import detect_pipeline_anomalies, historical_zscore
from agentic_data_platform.quality.reconciliation import (
    canonical_value,
    reconcile_bucket_hash,
    reconcile_hash,
    row_hash,
)


def test_canonical_hash_normalizes_cross_warehouse_values():
    left = {
        "id": 1,
        "amount": Decimal("10.5000"),
        "active": True,
        "event_at": datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc),
        "nullable": None,
    }
    right = dict(left)
    assert row_hash(left) == row_hash(right)
    assert canonical_value(Decimal("10.5000"))["value"] == "10.5"


def test_dataset_hash_is_order_independent_and_detects_change():
    source = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
    target = list(reversed(source))
    assert reconcile_hash(source, target)["status"] == "PASS"

    changed = [{"id": 1, "value": "a"}, {"id": 2, "value": "changed"}]
    result = reconcile_hash(source, changed)
    assert result["status"] == "FAIL"
    assert result["source_count"] == result["target_count"] == 2


def test_bucket_hash_localizes_mismatched_bucket():
    source = [{"id": value, "amount": value * 10} for value in range(1, 20)]
    target = [dict(row) for row in source]
    target[7]["amount"] = 999
    result = reconcile_bucket_hash(source, target, key_column="id", bucket_count=8)
    assert result["status"] == "FAIL"
    assert result["mismatch_count"] == 1
    assert result["mismatched_buckets"][0]["source"]["row_count"] >= 1


def test_proactive_anomaly_detects_business_issue_while_orchestration_green():
    result = detect_pipeline_anomalies({
        "airflow_state": "SUCCESS",
        "dbt_state": "SUCCESS",
        "payment_to_reservation_ratio": 0.79,
        "historical_payment_to_reservation_ratio": 0.97,
        "ratio_tolerance": 0.1,
        "source_count": 200_000,
        "target_count": 184_000,
        "source_target_ratio_tolerance": 0.01,
    })
    assert result["status"] == "ANOMALY"
    assert result["technical_state"] == {"airflow": "SUCCESS", "dbt": "SUCCESS"}
    assert {item["metric"] for item in result["findings"] if item["status"] == "ANOMALY"} == {
        "source_target_ratio",
        "payment_to_reservation_ratio",
    }


def test_historical_zscore_requires_history_and_detects_outlier():
    insufficient = historical_zscore("volume", 10, [9])
    assert insufficient.status == "INSUFFICIENT_HISTORY"
    outlier = historical_zscore("volume", 100, [10, 11, 9, 10, 10])
    assert outlier.status == "ANOMALY"
