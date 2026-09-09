from __future__ import annotations

import ast
import subprocess
import sys

from lib import ROOT


SCRIPT_NAMES = (
    "generate_data.py", "validate_files.py", "bootstrap_snowflake.py", "teardown_snowflake.py", "reset_testbed.py",
    "stage_internal_files.py", "upload_to_s3.py", "render_copy_commands.py", "run_copy_loads.py", "monitor_snowpipe.py",
    "monitor_streams.py", "consume_streams.py", "reconcile_pipeline.py", "validate_pipeline.py", "stage_failure_fixture.py",
    "run_failure_certification.py", "certify_failure_accuracy.py", "certify_with_ade.py", "run_dbt.py", "run_snowflake_dq.py", "run_e2e.py", "generate_final_report.py",
)


def test_every_python_script_has_help():
    for name in SCRIPT_NAMES:
        process = subprocess.run([sys.executable, str(ROOT / "scripts/hospitality_testbed" / name), "--help"], cwd=ROOT, text=True, capture_output=True, check=False)
        assert process.returncode == 0, (name, process.stderr)
        assert "usage:" in process.stdout.lower()


def test_shell_wrappers_are_strict():
    for path in (ROOT / "scripts/hospitality_testbed").glob("*.sh"):
        assert "set -euo pipefail" in path.read_text()


def test_airflow_source_defines_required_dags_and_parses():
    path = ROOT / "hospitality-snowflake-data-platform/airflow/dags/hospitality_testbed_dags.py"
    source = path.read_text()
    ast.parse(source)
    for dag_id in ("generate_testbed_data", "validate_landing_files", "upload_testbed_files", "snowflake_manual_backfill", "snowpipe_monitor", "raw_data_quality", "stream_monitor", "cdc_processing", "dbt_staging_build", "dbt_core_build", "dbt_marts_build", "reconciliation", "ade_snowflake_certification", "hospitality_end_to_end"):
        assert dag_id in source


def test_dbt_project_has_forty_models_and_required_tests():
    root = ROOT / "hospitality-snowflake-data-platform/dbt/testbed"
    models = list((root / "models").rglob("*.sql"))
    assert len(models) == 40
    required = {"stg_reservations", "dim_hotel", "fact_reservation", "mart_daily_occupancy", "mart_payment_reconciliation"}
    assert required <= {path.stem for path in models}
    assert len(list((root / "tests").glob("*.sql"))) >= 7
