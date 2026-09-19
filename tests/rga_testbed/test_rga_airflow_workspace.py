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


def test_generated_airflow_dag_uses_single_operator_workspace(tmp_path: Path):
    module = load_module(
        "rga_airflow_workspace_test",
        ROOT / "scripts" / "rga_testbed" / "generate_airflow_dag.py",
    )
    path = module.generate(tmp_path / "rga_synthetic_pipeline.py")
    dag = path.read_text(encoding="utf-8")

    assert 'WORKSPACE = os.environ.get("RGA_WORKSPACE"' in dag
    assert 'DATA_DIR = f"{WORKSPACE}/data"' in dag
    assert 'CDC_DIR = f"{WORKSPACE}/cdc"' in dag
    assert 'SQL_DIR = f"{WORKSPACE}/snowflake"' in dag
    assert 'DBT_DIR = f"{WORKSPACE}/dbt"' in dag
    assert 'RELEASE_DIR = f"{WORKSPACE}/release"' in dag
    assert 'SEMANTIC_DIR = f"{RELEASE_DIR}/semantic"' in dag

    assert "--output {DATA_DIR}" in dag
    assert "--input {DATA_DIR}" in dag
    assert "--output {SQL_DIR}/001_raw_tables.sql" in dag
    assert "--output {SQL_DIR}/002_load_raw.sql" in dag
    assert "--local-root {DATA_DIR}/csv" in dag
    assert "--output {CDC_DIR}" in dag
    assert "--output {SQL_DIR}/003_apply_cdc.sql" in dag
    assert "--output {DBT_DIR}" in dag
    assert "--output {RELEASE_DIR}" in dag

    assert "validate_synthetic_data" in dag
    assert (
        "generate_data >> validate_data >> generate_contracts >> bootstrap_snowflake"
        in dag
    )


def test_generated_airflow_cdc_path_is_default_off_and_semantically_validated(tmp_path: Path):
    module = load_module(
        "rga_airflow_cdc_test",
        ROOT / "scripts" / "rga_testbed" / "generate_airflow_dag.py",
    )
    dag = module.render_dag()

    assert '"apply_cdc": False' in dag
    assert "cdc_apply_gate" in dag
    assert "capture_cdc_semantic_baseline" in dag
    assert "apply_cdc" in dag
    assert "dbt_rebuild_after_cdc" in dag
    assert "verify_semantic_after_cdc" in dag
    assert "validate_cdc_application" in dag
    assert "validate_cdc_semantic_effects" in dag
