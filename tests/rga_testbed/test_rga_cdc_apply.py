from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_cdc_apply_sql_is_idempotent_and_audited(tmp_path: Path):
    module = load_module(
        "rga_cdc_apply_test",
        ROOT / "scripts" / "rga_testbed" / "generate_cdc_apply_sql.py",
    )
    source = tmp_path / "change_events.jsonl"
    source.write_text('{"event_id":"x"}\n', encoding="utf-8")
    sql = module.render(source, "RGA_SYNTHETIC_TESTBED")

    assert "RAW.RGA_CDC_STAGE" in sql
    assert "RAW.RGA_CDC_EVENTS" in sql
    assert "TMP_RGA_CDC_PENDING" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY EVENT:event_id::VARCHAR" in sql
    assert "AUDIT.CDC_EVENT_APPLICATIONS" in sql
    assert "A.STATUS = 'APPLIED'" in sql
    assert "MERGE INTO RAW.POLICIES" in sql
    assert "MERGE INTO RAW.PREMIUMS" in sql
    assert "MERGE INTO RAW.CLAIMS" in sql
    assert "'APPLIED'" in sql
    assert "unsupported and were deliberately not marked APPLIED" in sql
    assert "DELETE FROM" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()


def test_cdc_apply_sql_preserves_expected_mutation_semantics(tmp_path: Path):
    module = load_module(
        "rga_cdc_apply_semantics_test",
        ROOT / "scripts" / "rga_testbed" / "generate_cdc_apply_sql.py",
    )
    source = tmp_path / "change_events.jsonl"
    source.write_text("", encoding="utf-8")
    sql = module.render(source, "CUSTOM_DB")

    assert "USE DATABASE CUSTOM_DB;" in sql
    assert "EVENT:after:policy_status::VARCHAR AS POLICY_STATUS" in sql
    assert "EVENT:after:gross_premium::NUMBER(18,2) AS GROSS_PREMIUM" in sql
    assert "EVENT:after:ceded_premium::NUMBER(18,2) AS CEDED_PREMIUM" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "EVENT:after:reported_date::DATE AS REPORTED_DATE" in sql
    assert "_SOURCE_FILE = 'cdc:' || S.EVENT_ID" in sql


def test_snowflake_ddl_contains_cdc_storage_and_audit_objects():
    module = load_module(
        "rga_cdc_ddl_test",
        ROOT / "scripts" / "rga_testbed" / "generate_snowflake_ddl.py",
    )
    config = module.load_config(ROOT / "config" / "rga_domain.yml")
    ddl = module.compile_ddl(config, "RGA_SYNTHETIC_TESTBED")

    assert "CREATE FILE FORMAT IF NOT EXISTS RAW.FF_RGA_JSON" in ddl
    assert "CREATE STAGE IF NOT EXISTS RAW.RGA_CDC_STAGE" in ddl
    assert "CREATE TABLE IF NOT EXISTS RAW.RGA_CDC_EVENTS" in ddl
    assert "CREATE TABLE IF NOT EXISTS AUDIT.CDC_EVENT_APPLICATIONS" in ddl
    assert "EVENT VARIANT NOT NULL" in ddl
    assert "STATUS VARCHAR NOT NULL" in ddl
