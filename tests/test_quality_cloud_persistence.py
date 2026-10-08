from __future__ import annotations

import os

import pytest

from agentic_data_platform.quality.postgres_store import PostgresQualityStore
from agentic_data_platform.quality.store import QualityResult, SQLiteQualityStore
from agentic_data_platform.quality.store_factory import create_quality_store, quality_backend_name


def test_quality_factory_keeps_sqlite_as_local_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ADE_QUALITY_DATABASE_URL", raising=False)
    monkeypatch.setenv("ADE_QUALITY_DATABASE", str(tmp_path / "quality.db"))

    store = create_quality_store()

    assert isinstance(store, SQLiteQualityStore)
    assert quality_backend_name(store) == "sqlite"
    store.initialize()
    run_id = store.start_run("local-prototype")
    assert store.get_run(run_id)["status"] == "RUNNING"


def test_quality_factory_selects_postgres_without_connecting() -> None:
    store = create_quality_store("postgresql://ade:secret@db.internal:5432/ade")  # audit-safe-fixture

    assert isinstance(store, PostgresQualityStore)
    assert quality_backend_name(store) == "postgresql"
    assert store.dsn.endswith("/ade")


def test_quality_factory_fails_closed_for_unknown_remote_backend() -> None:
    with pytest.raises(ValueError, match="unsupported quality persistence scheme"):
        create_quality_store("redis://example/quality")


def _assert_quality_contract(store: SQLiteQualityStore | PostgresQualityStore) -> None:
    store.initialize()
    run_id = store.start_run(
        "prototype-quality-certification",
        details={"scenario": "row_count_regression", "source": "ci"},
    )
    result = QualityResult(
        check_id="customer_revenue_row_count",
        run_id=run_id,
        system="snowflake",
        layer="mart",
        asset="mart.customer_revenue",
        check_type="row_count",
        severity="ERROR",
        status="FAIL",
        observed_value=72,
        expected_value=100,
        batch_id="batch-prototype",
        details={"evidence": "deterministic-count"},
    )
    result_id = store.save_result(result)
    reconciliation_id = store.save_reconciliation(
        run_id,
        {
            "metric": "row_count",
            "status": "FAIL",
            "source_value": 100,
            "target_value": 72,
            "difference": -28,
        },
    )

    results = store.list_results(run_id)
    assert len(results) == 1
    assert results[0]["result_id"] == result_id
    assert results[0]["observed_value"] == 72
    assert results[0]["expected_value"] == 100
    assert results[0]["details"] == {"evidence": "deterministic-count"}

    reconciliations = store.recent_reconciliations()
    assert any(item["result_id"] == reconciliation_id and item["status"] == "FAIL" for item in reconciliations)

    summary = store.summary()
    assert summary["run_count"] >= 1
    assert summary["result_count"] >= 1
    assert summary["reconciliation_count"] >= 1
    assert summary["status_counts"]["FAIL"] >= 1
    assert summary["reconciliation_status_counts"]["FAIL"] >= 1

    store.complete_run(run_id, "FAIL")
    completed = store.get_run(run_id)
    assert completed is not None
    assert completed["status"] == "FAIL"
    assert completed["completed_at"] is not None

    with pytest.raises(KeyError, match="quality run not found"):
        store.complete_run("quality_run_missing", "PASS")
    with pytest.raises(ValueError, match="PASS, FAIL, or ERROR"):
        store.complete_run(run_id, "UNKNOWN")


def test_sqlite_quality_contract(tmp_path) -> None:
    _assert_quality_contract(SQLiteQualityStore(tmp_path / "quality-contract.db"))


def test_postgres_quality_contract() -> None:
    dsn = os.getenv("ADE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ADE_TEST_POSTGRES_DSN is not configured")
    _assert_quality_contract(PostgresQualityStore(dsn))
