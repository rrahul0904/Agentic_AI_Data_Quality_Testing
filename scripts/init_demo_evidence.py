#!/usr/bin/env python3
"""Seed deterministic local evidence for the v0.4 operator-console demo."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agentic_data_platform.quality.reconciliation import reconcile_row_count
from agentic_data_platform.quality.store import QualityResult, SQLiteQualityStore

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path(os.getenv("ADE_QUALITY_DATABASE", ROOT / ".ade" / "quality.db")).expanduser().resolve()

def add_result(store, run_id, *, check_id, asset, check_type, status, observed, expected,
               severity="ERROR", layer="RAW", system="snowflake", details=None):
    store.save_result(QualityResult(
        check_id=check_id, run_id=run_id, system=system, layer=layer, asset=asset,
        check_type=check_type, severity=severity, status=status,
        observed_value=observed, expected_value=expected, details=details or {},
    ))

def main() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    for candidate in (DATABASE, Path(str(DATABASE) + "-wal"), Path(str(DATABASE) + "-shm")):
        if candidate.exists():
            candidate.unlink()

    store = SQLiteQualityStore(DATABASE)
    store.initialize()

    failing_run = store.start_run(
        "reservation-ingestion-intentional-failure",
        details={"mode": "LOCAL_SIMULATION", "purpose": "prove fail-closed quality behavior"},
    )
    add_result(
        store, failing_run, check_id="reservation_row_count_parity",
        asset="RAW.ORACLE_RESERVATION", check_type="row_count", status="FAIL",
        observed=9998, expected=10000,
        details={"difference": 2, "tolerance": 0, "fixture": "intentional"},
    )
    add_result(
        store, failing_run, check_id="reservation_primary_key_not_null",
        asset="RAW.ORACLE_RESERVATION", check_type="not_null", status="PASS",
        observed=0, expected=0,
    )
    store.save_reconciliation(failing_run, reconcile_row_count(10000, 9998))
    store.complete_run(failing_run, "FAIL")

    clean_run = store.start_run(
        "reservation-ingestion-clean-fixture",
        details={"mode": "LOCAL_SIMULATION", "purpose": "prove clean data passes the same gates"},
    )
    add_result(
        store, clean_run, check_id="reservation_row_count_parity",
        asset="RAW.ORACLE_RESERVATION", check_type="row_count", status="PASS",
        observed=10000, expected=10000,
    )
    add_result(
        store, clean_run, check_id="reservation_primary_key_unique",
        asset="CORE.FACT_RESERVATION", check_type="unique", status="PASS",
        observed=0, expected=0, layer="CORE", system="dbt",
    )
    add_result(
        store, clean_run, check_id="payment_amount_non_negative",
        asset="CORE.FACT_PAYMENT", check_type="business_rule", status="PASS",
        observed=0, expected=0, layer="CORE", system="dbt",
    )
    store.save_reconciliation(clean_run, reconcile_row_count(10000, 10000))
    store.complete_run(clean_run, "PASS")
    print(json.dumps({"database": str(DATABASE), **store.summary()}, indent=2, default=str))

if __name__ == "__main__":
    main()
