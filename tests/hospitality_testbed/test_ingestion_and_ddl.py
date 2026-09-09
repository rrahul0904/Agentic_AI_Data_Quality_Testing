from __future__ import annotations

import yaml

from lib import ROOT, manifest_stage_path, render_sql, split_sql
from render_copy_commands import copy_commands
from run_snowflake_dq import rule_queries


def test_ingestion_catalog_has_required_format_split_and_pipes():
    catalog = yaml.safe_load((ROOT / "config/hospitality_ingestion.yml").read_text())["entities"]
    assert len(catalog) == 20
    assert sum(item["format"] == "csv" for item in catalog.values()) == 12
    assert sum(item["format"] == "parquet" for item in catalog.values()) == 8
    assert sum("snowpipe" in item for item in catalog.values()) == 6


def test_copy_rendering_is_manifest_bounded_and_metadata_driven(generated_dataset):
    _, manifest, _ = generated_dataset
    commands = copy_commands(manifest, "local")
    assert len(commands) == manifest["file_count"]
    assert all("FILES = (" in item["sql"] for item in commands)
    assert all("MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE" in item["sql"] for item in commands)
    assert all("INCLUDE_METADATA" in item["sql"] for item in commands)
    assert all("FORCE = FALSE" in item["sql"] for item in commands)
    assert all(f"generation_id={manifest['generation_id']}" in item["stage_file"] for item in commands)


def test_stage_paths_are_generation_isolated_below_pipe_prefix():
    item = {"file": "csv/reservations/year=2026/month=09/day=09/reservations_00001.csv"}
    path = manifest_stage_path(item, "gen_abc123")
    assert path == "csv/reservations/generation_id=gen_abc123/year=2026/month=09/day=09/reservations_00001.csv"


def test_snowflake_dq_has_one_read_only_query_per_configured_rule():
    configured = yaml.safe_load((ROOT / "config/hospitality_quality.yml").read_text())["rules"]
    queries = rule_queries("HOSPITALITY_TESTBED", "gen_abc123", "load_abc123", 26)
    assert len(queries) == len(configured) == 18
    assert {item["name"] for item in queries} == {item["name"] for item in configured}
    assert all(item["sql"].lstrip().upper().startswith("SELECT") for item in queries)


def test_snowflake_ddl_has_expected_objects_and_safe_templates():
    ddl_root = ROOT / "snowflake/testbed"
    ddl = "\n".join(path.read_text() for path in ddl_root.rglob("*.sql"))
    assert ddl.count("CREATE TABLE IF NOT EXISTS {{DATABASE}}.RAW.") == 20
    assert ddl.count("CREATE STREAM IF NOT EXISTS") == 5
    assert ddl.count("CREATE PIPE IF NOT EXISTS") == 6
    assert "STAGE_HOSPITALITY_INTERNAL" in ddl and "STAGE_HOSPITALITY_S3" in ddl
    assert "FF_HOSPITALITY_CSV" in ddl and "FF_HOSPITALITY_PARQUET" in ddl
    rendered = render_sql(ddl)
    assert "{{DATABASE}}" not in rendered
    assert "CREATE OR REPLACE PIPE" not in ddl
    assert "ALTER TASK" not in ddl


def test_file_formats_are_explicit():
    ddl = (ROOT / "snowflake/testbed/02_file_formats.sql").read_text()
    for option in ("TYPE = CSV", "FIELD_DELIMITER", "SKIP_HEADER", "FIELD_OPTIONALLY_ENCLOSED_BY", "NULL_IF", "EMPTY_FIELD_AS_NULL", "ERROR_ON_COLUMN_COUNT_MISMATCH", "COMPRESSION", "TIMESTAMP_FORMAT", "DATE_FORMAT"):
        assert option in ddl


def test_sql_splitter_preserves_semicolons_in_literals_and_comments():
    statements = split_sql("CREATE TABLE X(A VARCHAR COMMENT 'one;two'); -- three;four\nCREATE TABLE Y(B NUMBER);")
    assert len(statements) == 2
    assert "one;two" in statements[0]
    assert "three;four" in statements[1]
