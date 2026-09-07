from __future__ import annotations

import json
from pathlib import Path

from airflow.dags.job_catalog import INGESTION_JOBS
from data_generator.faker_config import get_scale
from data_generator.generate_file_data import FEEDS, generate
from data_generator.relational_exports import generate_relational_exports
from data_generator.source_catalog import ORACLE_TABLES, POSTGRES_TABLES
from quality.checks.validate_generated_files import validate_file


def test_source_catalogs_are_enterprise_sized_and_unique() -> None:
    assert len(ORACLE_TABLES) >= 100
    assert len(POSTGRES_TABLES) >= 100
    assert len(ORACLE_TABLES) == len(set(ORACLE_TABLES))
    assert len(POSTGRES_TABLES) == len(set(POSTGRES_TABLES))


def test_all_required_ingestion_jobs_are_declared() -> None:
    assert len(INGESTION_JOBS) == 40
    assert [item.dag_id[:2] for item in INGESTION_JOBS] == [f"{i:02d}" for i in range(1, 41)]
    assert {item.source for item in INGESTION_JOBS} == {"oracle", "postgres", "files"}


def test_scale_targets_match_brief() -> None:
    assert get_scale("small").events == 500_000
    assert get_scale("medium").reservations == 1_000_000
    assert get_scale("large").events == 100_000_000


def test_all_eighteen_file_feeds_generate_and_validate(tmp_path: Path) -> None:
    counts = generate("small", tmp_path, seed=7, max_rows=10)
    assert set(counts) == set(FEEDS)
    assert all(count >= 10 for count in counts.values())  # deliberate duplicates may add rows
    assert json.loads((tmp_path / "manifest.json").read_text())["seed"] == 7
    for filename in FEEDS:
        result = validate_file(tmp_path / filename)
        assert result["sampled_rows"] >= 10


def test_relational_export_generators_cover_entire_catalog(tmp_path: Path) -> None:
    oracle_counts = generate_relational_exports("oracle", "small", tmp_path, seed=7, max_rows=2)
    postgres_counts = generate_relational_exports("postgres", "small", tmp_path, seed=7, max_rows=2)
    assert set(oracle_counts) == set(ORACLE_TABLES)
    assert set(postgres_counts) == set(POSTGRES_TABLES)
    assert all(count == 2 for count in oracle_counts.values())
    assert all(count == 2 for count in postgres_counts.values())


def test_dbt_model_inventory_exceeds_minimum() -> None:
    project = Path(__file__).parents[1]
    models = list((project / "dbt" / "models").rglob("*.sql"))
    assert len(models) >= 30


def test_reservation_alias_dags_are_declared() -> None:
    dag_file = Path(__file__).parents[1] / "airflow" / "dags" / "reservation_aliases.py"
    text = dag_file.read_text(encoding="utf-8")
    for dag_id in (
        "oracle_reservation_ingest", "oracle_reservation_room_ingest", "oracle_guest_ingest",
        "oracle_room_ingest", "postgres_booking_attempt_ingest", "postgres_booking_confirmation_ingest",
        "postgres_payment_transaction_ingest", "postgres_refund_transaction_ingest", "hospitality_reservation_master",
    ):
        assert dag_id in text
