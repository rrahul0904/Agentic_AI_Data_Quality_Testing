from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InvestigationScenario:
    scenario_id: str
    title: str
    affected_asset: str
    business_concept: str
    source_systems: tuple[str, ...]
    comparisons: tuple[dict[str, Any], ...]
    signals: dict[str, Any]
    pipeline_path: tuple[str, ...]
    downstream_assets: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class FailureScenario:
    scenario_id: str
    title: str
    affected_asset: str
    business_concept: str
    source_systems: tuple[str, ...]
    comparisons: tuple[dict[str, Any], ...]
    signals: dict[str, Any]
    pipeline_path: tuple[str, ...]
    expected_root_cause: str
    expected_first_divergence: str
    remediation_action: str
    downstream_assets: tuple[str, ...] = ()
    description: str = ""
    after_fix: dict[str, Any] = field(default_factory=dict)

    def runtime_input(self) -> InvestigationScenario:
        """Return the only scenario shape that agents are allowed to receive."""
        return InvestigationScenario(
            scenario_id=self.scenario_id,
            title=self.title,
            affected_asset=self.affected_asset,
            business_concept=self.business_concept,
            source_systems=tuple(self.source_systems),
            comparisons=tuple(dict(item) for item in self.comparisons),
            signals=dict(self.signals),
            pipeline_path=tuple(self.pipeline_path),
            downstream_assets=tuple(self.downstream_assets),
            description=self.description,
        )

    def agent_context(self) -> dict[str, Any]:
        runtime = self.runtime_input()
        return {
            "scenario_id": runtime.scenario_id,
            "title": runtime.title,
            "affected_asset": runtime.affected_asset,
            "business_concept": runtime.business_concept,
            "source_systems": list(runtime.source_systems),
            "comparisons": [dict(item) for item in runtime.comparisons],
            "signals": dict(runtime.signals),
            "pipeline_path": list(runtime.pipeline_path),
            "downstream_assets": list(runtime.downstream_assets),
            "description": runtime.description,
        }


def _comparison(pair: str, status: str, **metrics: Any) -> dict[str, Any]:
    return {"pair": pair, "status": status, **metrics}


SCENARIOS: dict[str, FailureScenario] = {}


def _add(item: FailureScenario) -> None:
    SCENARIOS[item.scenario_id] = item


_add(FailureScenario(
    "watermark_defect",
    "Airflow green but payment watermark skips committed rows",
    "mart_payment_reconciliation",
    "payment",
    ("postgres", "snowflake"),
    (
        _comparison("source→raw", "FAIL", source_count=1_250_004, target_count=1_247_831, difference=2_173),
        _comparison("raw→staging", "PASS", source_count=1_247_831, target_count=1_247_831),
        _comparison("staging→intermediate", "PASS", source_count=1_247_831, target_count=1_247_831),
        _comparison("intermediate→mart", "PASS", source_count=1_247_831, target_count=1_247_831),
    ),
    {
        "airflow_state": "SUCCESS",
        "dbt_state": "SUCCESS",
        "source_max_timestamp": "2026-09-07T23:59:58+00:00",
        "extracted_max_timestamp": "2026-09-07T21:46:13+00:00",
        "persisted_watermark": "2026-09-07T23:59:59+00:00",
        "payment_volume_change_pct": -18.0,
        "reservation_volume_change_pct": -0.3,
        "payment_to_reservation_ratio": 0.79,
        "historical_payment_to_reservation_ratio": 0.97,
    },
    (
        "postgres.payment_transaction", "airflow.28_postgres_payment_transaction_ingest",
        "snowflake.RAW.POSTGRES_PAYMENT_TRANSACTION", "stg_postgres_payment_transaction",
        "int_payment_lifecycle", "fact_payment", "mart_payment_reconciliation",
    ),
    "WATERMARK_ADVANCED_BEYOND_EXTRACT",
    "source→raw",
    "RESET_WATERMARK_AND_BOUNDED_BACKFILL",
    ("stg_postgres_payment_transaction", "int_payment_lifecycle", "fact_payment", "mart_payment_reconciliation"),
    "The orchestrator reports success, but the persisted high-watermark moved past the last extracted record.",
    {"source_count": 1_250_004, "raw_count": 1_250_004, "business_metric_match": True},
))

_add(FailureScenario(
    "dbt_filter_defect", "dbt filter excludes shipped revenue", "fact_revenue", "revenue", ("snowflake",),
    (
        _comparison("source→raw", "PASS", source_count=10_000, target_count=10_000),
        _comparison("raw→staging", "PASS", source_count=10_000, target_count=10_000),
        _comparison("staging→intermediate", "FAIL", source_count=10_000, target_count=9_620, difference=380),
        _comparison("intermediate→mart", "PASS", source_count=9_620, target_count=9_620),
    ),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "filter_expression": "status = 'COMPLETE'", "valid_status_missing": "SHIPPED"},
    ("snowflake.RAW.ORDERS", "stg_orders", "int_revenue", "fact_revenue"),
    "DBT_FILTER_EXCLUDES_VALID_STATUS", "staging→intermediate", "PATCH_DBT_FILTER_AND_SELECTIVE_BUILD",
    ("int_revenue", "fact_revenue"),
))

_add(FailureScenario(
    "join_fanout", "multi-table dbt join duplicates payment rows", "fact_payment", "payment", ("snowflake",),
    (
        _comparison("source→raw", "PASS", source_count=50_000, target_count=50_000),
        _comparison("raw→staging", "PASS", source_count=50_000, target_count=50_000),
        _comparison("staging→intermediate", "FAIL", source_count=50_000, target_count=52_800, difference=2_800),
    ),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "join_cardinality": "many_to_many", "duplicate_business_keys": 2_800},
    ("RAW.PAYMENT", "stg_payment", "int_payment_lifecycle", "fact_payment"),
    "DBT_JOIN_FANOUT", "staging→intermediate", "PATCH_JOIN_CARDINALITY",
    ("int_payment_lifecycle", "fact_payment", "mart_payment_reconciliation"),
))

_add(FailureScenario(
    "incremental_predicate_defect", "late-arriving payment falls outside dbt incremental lookback", "fact_payment", "payment", ("snowflake",),
    (
        _comparison("source→raw", "PASS", source_count=80_000, target_count=80_000),
        _comparison("raw→staging", "PASS", source_count=80_000, target_count=80_000),
        _comparison("staging→core", "FAIL", source_count=80_000, target_count=79_740, difference=260),
    ),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "late_arriving_rows": 260, "incremental_lookback_hours": 24, "max_late_hours": 51},
    ("RAW.PAYMENT", "stg_payment", "fact_payment"),
    "DBT_INCREMENTAL_LATE_ARRIVAL_GAP", "staging→core", "WIDEN_INCREMENTAL_LOOKBACK_AND_REBUILD",
    ("fact_payment", "mart_payment_reconciliation"),
))

_add(FailureScenario(
    "duplicate_airflow_load", "Airflow retry re-loads an already committed batch", "RAW.PAYMENT", "payment", ("postgres", "snowflake"),
    (_comparison("source→raw", "FAIL", source_count=40_000, target_count=40_700, duplicates=700),),
    {"airflow_state": "SUCCESS", "task_try_number": 2, "duplicate_business_keys": 700, "idempotency_key_present": False},
    ("postgres.payment_transaction", "airflow.payment_ingestion", "snowflake.RAW.PAYMENT"),
    "AIRFLOW_RETRY_DUPLICATE_LOAD", "source→raw", "DELETE_DUPLICATE_BATCH_AND_RELOAD_IDEMPOTENTLY",
    ("RAW.PAYMENT", "stg_payment", "fact_payment"),
))

_add(FailureScenario(
    "snowflake_permission_failure", "Snowflake write permission failure", "RAW.PAYMENT", "payment", ("snowflake",),
    (_comparison("airflow_landing→raw", "FAIL", extracted_count=10_000, loaded_count=0),),
    {"airflow_state": "FAILED", "warehouse_error": "SQL access control error: insufficient privileges", "error_code": "42501"},
    ("airflow.payment_ingestion", "snowflake.RAW.PAYMENT"),
    "SNOWFLAKE_PERMISSION_DENIED", "airflow_landing→raw", "RESTORE_ROLE_GRANT_AND_RETRY_LOAD",
))

_add(FailureScenario(
    "partial_load", "Snowflake load omits one manifest file", "RAW.PAYMENT", "payment", ("files", "snowflake"),
    (_comparison("airflow_landing→raw", "FAIL", extracted_count=25_000, loaded_count=24_100, missing_files=1),),
    {"airflow_state": "SUCCESS", "manifest_files": 10, "loaded_files": 9, "rejected_rows": 0},
    ("files.payment_settlement", "airflow.settlement_ingestion", "snowflake.RAW.PAYMENT_SETTLEMENT"),
    "SNOWFLAKE_PARTIAL_LOAD", "airflow_landing→raw", "LOAD_MISSING_MANIFEST_FILE",
))

_add(FailureScenario(
    "schema_drift", "source adds incompatible payment column type", "RAW.PAYMENT", "payment", ("postgres", "snowflake"),
    (_comparison("source→raw", "FAIL", source_schema_version=12, target_schema_version=11),),
    {"airflow_state": "FAILED", "schema_drift": True, "column": "payment_amount", "source_type": "NUMERIC(20,4)", "target_type": "NUMBER(12,2)"},
    ("postgres.payment_transaction", "snowflake.RAW.PAYMENT"),
    "SOURCE_SCHEMA_DRIFT", "source→raw", "APPLY_COMPATIBLE_SCHEMA_MIGRATION",
))

_add(FailureScenario(
    "freshness_failure", "pipeline ran on stale upstream source", "RAW.RESERVATION", "reservation", ("oracle",),
    (_comparison("source_freshness", "FAIL", lag_minutes=185, sla_minutes=30),),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "freshness_lag_minutes": 185, "freshness_sla_minutes": 30},
    ("oracle.RESERVATION", "RAW.RESERVATION"),
    "SOURCE_FRESHNESS_BREACH", "source_freshness", "HOLD_PUBLICATION_AND_REFRESH_SOURCE",
))

_add(FailureScenario(
    "null_spike", "guest identifier null rate spikes", "stg_oracle_reservation", "reservation", ("oracle",),
    (_comparison("raw→staging", "FAIL", historical_null_pct=0.2, current_null_pct=14.8),),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "null_spike": True, "column": "guest_id", "historical_null_pct": 0.2, "current_null_pct": 14.8},
    ("RAW.RESERVATION", "stg_oracle_reservation"),
    "SOURCE_NULL_SPIKE", "raw→staging", "QUARANTINE_BATCH_AND_VALIDATE_SOURCE_CONTRACT",
))

_add(FailureScenario(
    "revenue_reconciliation", "mart revenue differs from certified core revenue", "mart_executive_daily_kpis", "revenue", ("snowflake",),
    (_comparison("core→mart", "FAIL", source_amount=18_927_441.0, target_amount=18_404_127.0, difference=523_314.0),),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "revenue_variance": 523_314.0},
    ("fact_payment", "mart_executive_daily_kpis"),
    "REVENUE_TRANSFORMATION_MISMATCH", "core→mart", "REBUILD_AFFECTED_MART_AFTER_TRANSFORMATION_REVIEW",
))

_add(FailureScenario(
    "referential_integrity", "reservations reference missing guest records", "stg_oracle_reservation", "reservation", ("oracle",),
    (_comparison("raw→staging", "FAIL", orphan_keys=91),),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "orphan_guest_keys": 91},
    ("RAW.GUEST", "RAW.RESERVATION", "stg_oracle_reservation"),
    "MISSING_CUSTOMER_REFERENCE", "raw→staging", "RELOAD_GUEST_KEYS_BEFORE_RESERVATIONS",
))

_add(FailureScenario(
    "cdc_event_loss", "CDC sequence contains a missing range", "RAW.BOOKING_CONFIRMATION", "booking", ("postgres",),
    (_comparison("source→raw", "FAIL", expected_events=12_000, actual_events=11_740, missing_events=260),),
    {"airflow_state": "SUCCESS", "cdc_gap": True, "missing_sequence_start": 88120, "missing_sequence_end": 88379},
    ("postgres.booking_confirmation", "RAW.BOOKING_CONFIRMATION"),
    "CDC_EVENT_GAP", "source→raw", "REPLAY_CDC_SEQUENCE_RANGE",
))

_add(FailureScenario(
    "out_of_order_event", "late update arrives behind current state", "RAW.RESERVATION_STATUS_HISTORY", "reservation", ("oracle",),
    (_comparison("source→raw", "FAIL", stale_versions=43),),
    {"airflow_state": "SUCCESS", "out_of_order_events": 43, "event_time_ordering": False},
    ("oracle.RESERVATION_STATUS_HISTORY", "RAW.RESERVATION_STATUS_HISTORY"),
    "OUT_OF_ORDER_EVENT", "source→raw", "REPLAY_AND_MERGE_BY_EVENT_TIME",
))

_add(FailureScenario(
    "dbt_test_failure", "dbt uniqueness test fails", "fact_reservation", "reservation", ("snowflake",),
    (_comparison("dbt_test", "FAIL", failing_rows=34),),
    {"airflow_state": "SUCCESS", "dbt_state": "FAILED", "dbt_test_name": "unique_fact_reservation_reservation_id", "failing_rows": 34},
    ("stg_oracle_reservation", "fact_reservation"),
    "DBT_TEST_FAILURE", "dbt_test", "FIX_DUPLICATE_GRAIN_AND_REBUILD",
))

_add(FailureScenario(
    "dbt_compilation_failure", "dbt compiled SQL references missing column", "fact_payment", "payment", ("snowflake",),
    (_comparison("dbt_compile", "FAIL", compile_errors=1),),
    {"airflow_state": "SUCCESS", "dbt_state": "ERROR", "compile_error": "invalid identifier PAYMENT_AMT"},
    ("stg_postgres_payment_transaction", "fact_payment"),
    "DBT_COMPILATION_FAILURE", "dbt_compile", "PATCH_MODEL_COLUMN_REFERENCE",
))

_add(FailureScenario(
    "airflow_task_failure", "Airflow extractor task fails", "RAW.PAYMENT", "payment", ("postgres",),
    (_comparison("airflow_extract", "FAIL", extracted_rows=0),),
    {"airflow_state": "FAILED", "task_state": "FAILED", "task_id": "extract", "error": "source connection timeout"},
    ("postgres.payment_transaction", "airflow.payment_ingestion"),
    "AIRFLOW_TASK_FAILURE", "airflow_extract", "RETRY_AFTER_SOURCE_CONNECTIVITY_CHECK",
))

_add(FailureScenario(
    "airflow_green_data_bad", "all orchestration is green while payment completeness degrades", "mart_payment_reconciliation", "payment", ("postgres", "snowflake"),
    (
        _comparison("source→raw", "FAIL", source_count=200_000, target_count=184_000, difference=16_000),
        _comparison("raw→staging", "PASS", source_count=184_000, target_count=184_000),
    ),
    {"airflow_state": "SUCCESS", "dbt_state": "SUCCESS", "payment_volume_change_pct": -18.0, "reservation_volume_change_pct": 0.1, "payment_to_reservation_ratio": 0.79, "historical_payment_to_reservation_ratio": 0.97},
    ("postgres.payment_transaction", "airflow.payment_ingestion", "snowflake.RAW.PAYMENT", "stg_payment", "fact_payment", "mart_payment_reconciliation"),
    "BUSINESS_COMPLETENESS_ANOMALY", "source→raw", "BOUNDED_SOURCE_TO_RAW_RECONCILIATION_AND_RELOAD",
    ("stg_payment", "fact_payment", "mart_payment_reconciliation"),
))


def scenario_catalog() -> list[dict[str, Any]]:
    """Public scenario catalog. Benchmark ground truth is intentionally omitted."""
    return [
        {
            "scenario_id": item.scenario_id,
            "title": item.title,
            "affected_asset": item.affected_asset,
        }
        for item in SCENARIOS.values()
    ]


def benchmark_catalog() -> list[dict[str, Any]]:
    """Private deterministic benchmark ledger with expected labels."""
    return [
        {
            "scenario_id": item.scenario_id,
            "title": item.title,
            "affected_asset": item.affected_asset,
            "expected_first_divergence": item.expected_first_divergence,
            "expected_root_cause": item.expected_root_cause,
        }
        for item in SCENARIOS.values()
    ]


def get_scenario(scenario_id: str) -> FailureScenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"unknown agentic failure scenario: {scenario_id}") from exc
